from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .assessment_engine import AssessmentResponseError, build_explicit_unknown_assessment
from .config import ASSESSMENT_CASE_BATCH_SIZE, ASSESSMENT_JOB_LEASE_SECONDS
from .models import (
    AnswerAttempt,
    AssessmentBatch,
    AssessmentRun,
    CandidateProfile,
    EvidenceSpan,
    InterviewQuestion,
    InterviewReport,
    InterviewSession,
    OperationJob,
    RubricObservation,
    ensure_utc,
    utc_now,
)
from .profile_engine import update_candidate_profile
from .followup_flow import answered_followups_by_question
from .practice_flow import sync_practice_recommendation
from .providers import AssessmentProvider, AssessmentProviderError, BatchAssessmentCase
from .reporting_flow import persist_interview_report
from .rubrics import build_rubric
from .workflow_common import (
    ConflictError,
    _append_job_event,
    _get_active_session,
    _hash_payload,
    _question_spec,
)

def _create_batch_job(
    db: Session,
    session: InterviewSession,
    answers: list[AnswerAttempt],
    *,
    lease_seconds: int | None = None,
) -> OperationJob:
    request_hash = _hash_payload(
        {
            "session_id": session.id,
            "answers": [
                {
                    "id": answer.id,
                    "status": answer.status,
                    "hash": answer.answer_text_hash,
                }
                for answer in answers
            ],
        }
    )
    active_job = db.scalar(
        select(OperationJob)
        .where(
            OperationJob.session_id == session.id,
            OperationJob.operation_kind == "batch_assessment",
            OperationJob.request_hash == request_hash,
            OperationJob.status.in_(("pending", "running")),
        )
        .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
    )
    if active_job is not None:
        reference_time = active_job.started_at or active_job.created_at
        if reference_time is not None:
            age_seconds = (utc_now() - ensure_utc(reference_time)).total_seconds()
            lease = ASSESSMENT_JOB_LEASE_SECONDS if lease_seconds is None else lease_seconds
            if age_seconds > lease:
                stale_batch = (
                    db.get(AssessmentBatch, active_job.assessment_batch_id)
                    if active_job.assessment_batch_id
                    else None
                )
                active_job.status = "failed"
                active_job.current_stage = "failed"
                active_job.error_code = "stale_job"
                active_job.error_message = "上一轮评分任务已超时，已允许重新生成"
                active_job.finished_at = utc_now()
                if stale_batch is not None and stale_batch.status in {"pending", "running"}:
                    stale_batch.status = "failed"
                    stale_batch.error_code = "stale_job"
                    stale_batch.error_message = active_job.error_message
                    stale_batch.finished_at = utc_now()
                    for stale_run in db.scalars(
                        select(AssessmentRun).where(
                            AssessmentRun.assessment_batch_id == stale_batch.id,
                            AssessmentRun.status == "pending",
                        )
                    ):
                        stale_run.error_code = "stale_job"
                        stale_run.error_reason = active_job.error_message
                _append_job_event(db, active_job, "error", active_job.progress, active_job.error_message)
                db.commit()
                active_job = None
    if active_job is not None:
        return active_job
    previous_attempt = db.scalar(
        select(func.max(OperationJob.attempt_number)).where(
            OperationJob.session_id == session.id,
            OperationJob.operation_kind == "batch_assessment",
        )
    )
    job = OperationJob(
        id=str(uuid4()),
        user_id=session.user_id,
        session_id=session.id,
        operation_kind="batch_assessment",
        idempotency_key=f"{session.id}:{request_hash}:{(previous_attempt or 0) + 1}",
        request_hash=request_hash,
        status="pending",
        progress=0,
        current_stage="queued",
        provider="assessment_provider",
        attempt_number=(previous_attempt or 0) + 1,
    )
    db.add(job)
    db.flush()
    _append_job_event(db, job, "queued", 0, "已记录本场回答，等待分析")
    return job

def _batch_status(runs: list[AssessmentRun]) -> str:
    statuses = {run.status for run in runs}
    if "pending" in statuses:
        return "pending"
    if "rejected" in statuses:
        return "rejected"
    if "disputed" in statuses:
        return "disputed"
    if "invalid" in statuses:
        return "invalid"
    return "valid"


def _verifier_entries(case: BatchAssessmentCase, result) -> list[dict]:
    rubric_by_id = {item.rubric_id: item for item in build_rubric(case.question).items}
    return [
        {
            "rubric_id": item.rubric_id,
            "criterion": rubric_by_id[item.rubric_id].criterion,
            "quoted_text": item.quoted_text,
            "level": item.level,
            "question": case.question.prompt,
            "answer": case.answer_text,
        }
        for item in result.rubric_items
        if item.validity == "valid"
    ]

def _batch_result_response(
    db: Session,
    answers: list[AnswerAttempt],
    total_count: int,
    batch_id: str | None,
) -> dict:
    runs = [
        run
        for answer in answers
        if answer.status != "skipped"
        for run in [_latest_assessment_run(db, answer.id)]
        if run is not None
    ]
    job = None
    session_id = answers[0].session_id if answers else None
    if batch_id:
        job = db.scalar(
            select(OperationJob).where(OperationJob.assessment_batch_id == batch_id)
        )
    if job is None and session_id:
        job = db.scalar(
            select(OperationJob)
            .where(OperationJob.session_id == session_id)
            .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
        )
    return {
        "status": _batch_status(runs) if runs else "valid",
        "batch_id": batch_id,
        "job_id": job.id if job else None,
        "job_status": job.status if job else None,
        "job_error_code": job.error_code if job else None,
        "job_error_message": job.error_message if job else None,
        "evaluated_count": len(runs),
        "total_count": total_count,
        "assessments": [
            {
                "answer_id": answer.id,
                "question_id": answer.question_id,
                "assessment": _assessment_response(run, db),
            }
            for answer in answers
            if answer.status != "skipped"
            for run in [_latest_assessment_run(db, answer.id)]
            if run is not None
        ],
    }

def _split_assessment_cases(
    cases: list[BatchAssessmentCase],
    batch_size: int,
) -> list[tuple[BatchAssessmentCase, ...]]:
    size = max(1, batch_size)
    return [tuple(cases[index : index + size]) for index in range(0, len(cases), size)]


def build_graph_assessment_payload(graph_state: Mapping) -> list[dict]:
    """Build blind scoring inputs from a finalized graph transcript."""

    plan = [item for item in graph_state.get("plan", []) if isinstance(item, Mapping)]
    messages = [item for item in graph_state.get("messages", []) if isinstance(item, Mapping)]
    coverage = graph_state.get("coverage", {})
    coverage = coverage if isinstance(coverage, Mapping) else {}
    conflicts = graph_state.get("conflicts", [])
    conflicts = conflicts if isinstance(conflicts, list) else []
    result: list[dict] = []
    for node in plan:
        node_id = str(node.get("node_id", ""))
        node_messages = [
            item for item in messages if str(item.get("node_id", "")) == node_id
        ]
        question = next(
            (
                str(item.get("content", ""))
                for item in node_messages
                if item.get("role") == "interviewer"
            ),
            str(node.get("opening_question", "")),
        )
        answer = next(
            (
                str(item.get("content", ""))
                for item in reversed(node_messages)
                if item.get("role") == "candidate"
            ),
            "",
        )
        result.append(
            {
                "plan_node_id": node_id,
                "node_kind": str(node.get("kind", "")),
                "question": question,
                "answer": answer,
                "rubric_ids": [
                    str(item) for item in node.get("rubric_ids", []) if str(item).strip()
                ],
                "required_targets": [
                    str(item)
                    for item in node.get("required_targets", [])
                    if str(item).strip()
                ],
                "covered_targets": [
                    str(item)
                    for item in coverage.get(node_id, [])
                    if str(item).strip()
                ],
                "conflicts": [
                    str(item.get("detail", ""))
                    for item in conflicts
                    if isinstance(item, Mapping)
                    and str(item.get("target", "")) == str(node.get("kind", ""))
                ],
            }
        )
    return result


def _plan_node_id(question: InterviewQuestion, session: InterviewSession) -> str | None:
    if session.mode != "graph":
        return None
    value = str(question.knowledge_point_id or "")
    return value.removeprefix("graph.") or None

def assess_session(
    db: Session,
    session_id: str,
    assessment_provider: AssessmentProvider,
    *,
    profile_updater: Callable[..., CandidateProfile] | None = None,
    batch_job_creator: Callable[..., OperationJob] | None = None,
) -> dict:
    """Evaluate all completed answers with one provider call."""
    profile_updater = profile_updater or update_candidate_profile
    batch_job_creator = batch_job_creator or _create_batch_job
    session = _get_active_session(db, session_id)
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.order)
        )
    )
    if session.mode == "graph":
        session.total_questions = len(questions)
        if session.status != "completed":
            raise ConflictError("面试尚未完成")
    answers = list(
        db.scalars(
            select(AnswerAttempt)
            .where(AnswerAttempt.session_id == session_id)
            .order_by(AnswerAttempt.created_at, AnswerAttempt.id)
        )
    )
    answered_question_ids = {answer.question_id for answer in answers}
    missing_count = len(questions) - len(answered_question_ids)
    if missing_count:
        raise ConflictError(f"面试尚未完成，还缺少 {missing_count} 道题")

    scored_answers = [answer for answer in answers if answer.status != "skipped"]
    existing_runs = {
        answer.id: _latest_assessment_run(db, answer.id) for answer in scored_answers
    }
    if scored_answers and all(
        run is not None and run.status == "valid" for run in existing_runs.values()
    ):
        batch_id = next(
            (run.batch_id for run in existing_runs.values() if run and run.batch_id),
            None,
        )
        # Scoring may have succeeded before report/profile persistence failed.
        # Rebuild derived records locally rather than calling the model again.
        profile = db.get(CandidateProfile, session.profile_id) if session.profile_id else None
        report_query = select(InterviewReport).where(
            InterviewReport.session_id == session_id,
            InterviewReport.status.in_(("ready", "partial")),
        )
        report_query = report_query.where(
            InterviewReport.assessment_batch_id == batch_id
            if batch_id
            else InterviewReport.assessment_batch_id.is_(None)
        )
        report = db.scalar(report_query.order_by(InterviewReport.version.desc()))
        if report is None or profile is None or profile.current_snapshot_id is None:
            try:
                if report is None:
                    persist_interview_report(
                        db,
                        session_id,
                        assessment_batch_id=batch_id,
                        status="ready",
                        commit=False,
                    )
                if profile is None or profile.current_snapshot_id is None:
                    profile_updater(db, session_id, commit=False)
                sync_practice_recommendation(db, session)
                db.commit()
            except Exception:
                db.rollback()
                raise
        return _batch_result_response(db, answers, len(questions), batch_id)
    if not scored_answers:
        return _batch_result_response(db, answers, len(questions), None)

    question_by_id = {question.id: question for question in questions}
    followups_by_question = answered_followups_by_question(db, session_id)
    answers_to_evaluate = [
        answer
        for answer in scored_answers
        if existing_runs[answer.id] is None or existing_runs[answer.id].status != "valid"
    ]
    evaluator = getattr(assessment_provider, "evaluator", "siliconflow-blind-rubric-v1")
    batch_id = str(uuid4())
    job = batch_job_creator(db, session, scored_answers)
    job.prompt_version = getattr(assessment_provider, "prompt_version", None)
    if job.assessment_batch_id:
        return _batch_result_response(
            db,
            answers,
            len(questions),
            job.assessment_batch_id,
        )
    batch = AssessmentBatch(
        id=batch_id,
        session_id=session.id,
        operation_job_id=job.id,
        attempt_number=job.attempt_number,
        evaluator=evaluator,
        status="pending",
    )
    db.add(batch)
    db.flush()
    job.assessment_batch_id = batch.id
    db.commit()
    job.status = "running"
    job.started_at = utc_now()
    job.current_stage = "scoring"
    job.progress = 20
    _append_job_event(db, job, "stage", 20, "正在分析本场回答")
    db.commit()

    runs_by_answer: dict[str, AssessmentRun] = {}
    for answer in answers_to_evaluate:
        question = question_by_id[answer.question_id]
        rubric = build_rubric(_question_spec(question))
        run = AssessmentRun(
            id=str(uuid4()),
            answer_id=answer.id,
            question_id=question.id,
            plan_node_id=_plan_node_id(question, session),
            evaluator=evaluator,
            rubric_version=rubric.version,
            status="pending",
            attempt_number=(existing_runs[answer.id].attempt_number + 1)
            if existing_runs[answer.id] is not None
            else 1,
            batch_id=batch_id,
            assessment_batch_id=batch.id,
        )
        db.add(run)
        runs_by_answer[answer.id] = run
    db.commit()

    cases: list[BatchAssessmentCase] = []
    for answer in answers_to_evaluate:
        question = question_by_id[answer.question_id]
        question_spec = _question_spec(question)
        if answer.status == "explicit_unknown":
            result = build_explicit_unknown_assessment(
                question_spec,
                answer.answer_text,
                evaluator=evaluator,
            )
            _persist_rubric_result(db, runs_by_answer[answer.id], result)
            run = runs_by_answer[answer.id]
            run.status = "valid"
            run.aggregate_level = result.level
            run.aggregate_confidence = result.confidence
            run.commentary = "这题选择了直接说不知道，练习时可以先把最核心的概念补上。"
        else:
            round_followups = followups_by_question.get(answer.question_id) or []
            cases.append(
                BatchAssessmentCase(
                    answer_id=answer.id,
                    question_id=question.id,
                    question=question_spec,
                    answer_text=answer.answer_text,
                    followup_question="\n".join(
                        f"追问{index}：{f.question_text}"
                        for index, f in enumerate(round_followups, start=1)
                    ),
                    followup_text="\n".join(
                        (f.answer_text or "") for f in round_followups
                    ),
                    case_ref=f"c{len(cases) + 1}",
                )
            )
    db.commit()

    chunks = _split_assessment_cases(cases, ASSESSMENT_CASE_BATCH_SIZE)
    failed_chunks: list[tuple[str, str]] = []
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0}
    verification_pairs: list[tuple[BatchAssessmentCase, object]] = []
    successful_case_count = sum(
        1 for answer in scored_answers if answer.status == "explicit_unknown"
    )

    # 批次并发执行：评分是最长的等待，2-3 批并发可将墙钟时间除以批数。
    # provider 调用无共享状态；DB 写回保持在主线程按批有序进行。
    from concurrent.futures import ThreadPoolExecutor

    chunk_results: dict[int, object] = {}
    chunk_errors: dict[int, tuple[str, str]] = {}

    transient_codes = {"provider_timeout", "provider_rate_limited", "provider_connection_failed", "provider_unavailable"}

    def _run_chunk(index: int, chunk: tuple) -> None:
        # 仅瞬态错误（超时/限流/连接）自动重试一次；响应格式错误由宽容解析处理
        for attempt in (1, 2):
            try:
                chunk_results[index] = assessment_provider.assess_batch(chunk)
                return
            except Exception as exc:
                transient = (
                    isinstance(exc, AssessmentProviderError) and exc.code in transient_codes
                )
                if not transient or attempt == 2:
                    code = (
                        exc.code
                        if isinstance(exc, (AssessmentProviderError, AssessmentResponseError))
                        else "system_error"
                    )
                    chunk_errors[index] = (code, str(exc))
                    return
                time.sleep(1.0)

    with ThreadPoolExecutor(max_workers=min(3, max(1, len(chunks)))) as pool:
        futures = [pool.submit(_run_chunk, index, chunk) for index, chunk in enumerate(chunks, start=1)]
        for future in futures:
            future.result()

    # 响应格式类错误码 → 拒绝该批回答；其余（瞬态/系统）错误 → 保持待重试。
    response_error_codes = {
        "invalid_batch_case",
        "invalid_model_response",
        "invalid_rubric",
        "invalid_level",
        "invalid_evidence",
        "invalid_evidence_range",
        "invalid_confidence",
        "answer_hash_mismatch",
    }

    def _fail_chunk(chunk: tuple, code: str, message: str, status: str) -> None:
        db.rollback()
        for case in chunk:
            run = runs_by_answer[case.answer_id]
            run.status = status
            run.error_code = code
            run.error_reason = message[:500]
        failed_chunks.append((code, message))
        db.commit()

    for chunk_index, chunk in enumerate(chunks, start=1):
        error = chunk_errors.get(chunk_index)
        if error is not None:
            code, message = error
            _fail_chunk(chunk, code, message, "rejected" if code in response_error_codes else "pending")
            continue
        try:
            results = chunk_results[chunk_index]
            for key, value in getattr(assessment_provider, "last_usage", {}).items():
                if isinstance(value, int):
                    usage_totals[key] = usage_totals.get(key, 0) + value
            expected_keys = {(case.answer_id, case.question_id) for case in chunk}
            chunk_cases = {c.answer_id: c for c in chunk}
            actual_keys = {(item.answer_id, item.question_id) for item in results}
            if actual_keys != expected_keys or len(results) != len(actual_keys):
                raise AssessmentResponseError("invalid_batch_case", "批量评分结果与回答不匹配")
            for item in results:
                run = runs_by_answer[item.answer_id]
                _persist_rubric_result(db, run, item.result)
                run.commentary = item.commentary or None
                if item.result.rubric_items and all(
                    observation.validity == "valid" for observation in item.result.rubric_items
                ):
                    run.status = "valid"
                    run.aggregate_level = item.result.level
                    run.aggregate_confidence = item.result.confidence
                else:
                    run.status = "invalid"
                    run.error_code = "invalid_evidence"
                    run.error_reason = "至少一个 Rubric 证据未通过完整性校验"
                if run.status == "valid":
                    verification_pairs.append((chunk_cases[item.answer_id], item.result))
            successful_case_count += len(results)
            db.commit()
            progress = 20 + int(70 * chunk_index / max(1, len(chunks)))
            job.progress = progress
            _append_job_event(db, job, "stage", progress, f"已完成 {chunk_index}/{len(chunks)} 批回答")
            db.commit()
        except AssessmentResponseError as exc:
            _fail_chunk(chunk, exc.code, str(exc), "rejected")
        except Exception as exc:
            code = exc.code if isinstance(exc, AssessmentProviderError) else "system_error"
            _fail_chunk(chunk, code, str(exc), "pending")

    # 复核阶段：verifier 检查"引用是否与考察点相关、是否支持该等级"。
    # 复核失败不阻塞主评分；引用不相关 → 降级 invalid；等级偏差 >= 2 → 自动重评一次。
    verifier = getattr(assessment_provider, "verify_batch", None)
    if verifier is not None and verification_pairs:
        job.current_stage = "verifying"
        job.progress = min(95, job.progress + 5)
        _append_job_event(db, job, "stage", job.progress, "正在复核评分结果")
        db.commit()
        # 复核调用并发执行（每 case 一次调用），DB 处理保持在主线程
        from concurrent.futures import ThreadPoolExecutor

        verify_results: dict[int, dict | None] = {}
        with ThreadPoolExecutor(max_workers=min(3, max(1, len(verification_pairs)))) as pool:
            futures = {
                index: pool.submit(verifier, _verifier_entries(case, result))
                for index, (case, result) in enumerate(verification_pairs)
                if runs_by_answer[case.answer_id].status == "valid"
                and result.rubric_items
            }
            for index, future in futures.items():
                try:
                    verify_results[index] = future.result()
                except Exception as exc:
                    verify_results[index] = None
                    _append_job_event(
                        db, job, "error", job.progress,
                        f"复核未完成，保留原评分：{str(exc)[:200]}",
                    )
                    db.commit()
        for index, (case, result) in enumerate(verification_pairs):
            if index not in verify_results or verify_results[index] is None:
                continue
            run = runs_by_answer[case.answer_id]
            if run.status != "valid" or not result.rubric_items:
                continue
            verdicts = verify_results[index]
            needs_rerun = False
            for observation in db.scalars(
                select(RubricObservation).where(
                    RubricObservation.assessment_run_id == run.id
                )
            ):
                verdict = verdicts.get(observation.rubric_id)
                if not verdict:
                    continue
                if not verdict["quote_relevant"]:
                    observation.validity = "invalid"
                    observation.invalid_reason = "复核：引用与考察点不相关"
                    run.status = "invalid"
                    run.error_code = "invalid_evidence"
                    run.error_reason = "复核：引用与考察点不相关"
                elif (
                    not verdict["level_supported"]
                    and verdict["suggested_level"] is not None
                    and abs(verdict["suggested_level"] - observation.level) >= 2
                ):
                    needs_rerun = True
            db.commit()
            if needs_rerun:
                rerun = AssessmentRun(
                    id=str(uuid4()),
                    answer_id=run.answer_id,
                    question_id=run.question_id,
                    plan_node_id=run.plan_node_id,
                    evaluator=evaluator,
                    rubric_version=run.rubric_version,
                    status="pending",
                    attempt_number=run.attempt_number + 1,
                    batch_id=batch_id,
                    assessment_batch_id=batch.id,
                )
                db.add(rerun)
                db.commit()
                try:
                    rerun_results = assessment_provider.assess_batch([case])
                    for item in rerun_results:
                        _persist_rubric_result(db, rerun, item.result)
                        rerun.commentary = item.commentary or None
                        if item.result.rubric_items and all(
                            o.validity == "valid" for o in item.result.rubric_items
                        ):
                            rerun.status = "valid"
                            rerun.aggregate_level = item.result.level
                            rerun.aggregate_confidence = item.result.confidence
                        else:
                            rerun.status = "disputed"
                            rerun.error_code = "verifier_dispute"
                            rerun.error_reason = "复核与评分仍存在分歧，已保留两次结果"
                    runs_by_answer[case.answer_id] = rerun
                except Exception as exc:
                    rerun.status = "disputed"
                    rerun.error_code = "verifier_dispute"
                    rerun.error_reason = str(exc)[:500]
                db.commit()

    latest_runs_for_session = [
        runs_by_answer.get(answer.id) or existing_runs[answer.id]
        for answer in scored_answers
        if runs_by_answer.get(answer.id) is not None or existing_runs[answer.id] is not None
    ]
    batch_status = _batch_status(latest_runs_for_session)
    first_failure = failed_chunks[0] if failed_chunks else None
    has_previous_valid_result = any(
        run is not None and run.status == "valid" for run in existing_runs.values()
    )
    if successful_case_count or has_previous_valid_result:
        try:
            persist_interview_report(
                db,
                session_id,
                assessment_batch_id=batch_id,
                status="ready" if batch_status == "valid" else "partial",
                commit=False,
            )
            if batch_status == "valid":
                profile_updater(db, session_id, commit=False)
            sync_practice_recommendation(db, session)
            batch.status = "valid" if batch_status == "valid" else "partial"
            batch.finished_at = utc_now()
            if first_failure:
                batch.error_code, batch.error_message = first_failure[0], first_failure[1][:500]
            elif batch_status != "valid":
                batch.error_code = "invalid_evidence"
                batch.error_message = "部分回答的证据未通过校验，已保存可用结果"
            job.status = "succeeded" if batch_status == "valid" else "partial"
            job.progress = 100
            job.current_stage = "completed"
            job.finished_at = utc_now()
            job.error_code = batch.error_code
            job.error_message = batch.error_message
            job.raw_response_json = json.dumps(
                {
                    "case_count": len(cases),
                    "successful_case_count": successful_case_count,
                    "successful_chunk_count": len(chunks) - len(failed_chunks),
                    "failed_chunk_count": len(failed_chunks),
                    "usage": usage_totals,
                },
                ensure_ascii=False,
            )
            _append_job_event(
                db,
                job,
                "completed",
                100,
                "本场分析完成" if batch_status == "valid" else "本场分析完成，但部分回答未通过校验",
            )
            db.commit()
        except Exception as exc:
            _mark_batch_failed(db, job.id, batch.id, "system_error", str(exc), rejected=False)
    else:
        error_code, error_message = first_failure or ("system_error", "没有获得可用的评分结果")
        _mark_batch_failed(db, job.id, batch.id, error_code, error_message, rejected=False)

    return _batch_result_response(db, answers, len(questions), batch_id)

def _mark_batch_failed(
    db: Session,
    job_id: str,
    batch_id: str,
    error_code: str,
    error_message: str,
    *,
    rejected: bool,
) -> None:
    """Record failure after rolling back all in-flight scoring/report changes."""
    db.rollback()
    job = db.get(OperationJob, job_id)
    batch = db.get(AssessmentBatch, batch_id)
    if job is None or batch is None:
        raise RuntimeError("assessment failure records are missing")
    runs = list(
        db.scalars(
            select(AssessmentRun).where(
                AssessmentRun.assessment_batch_id == batch_id
            )
        )
    )
    for run in runs:
        if run.status == "pending":
            if rejected:
                run.status = "rejected"
            run.error_code = error_code
            run.error_reason = error_message[:500]
    batch.status = "failed"
    batch.error_code = error_code
    batch.error_message = error_message[:500]
    batch.finished_at = utc_now()
    job.status = "failed"
    job.current_stage = "failed"
    job.error_code = error_code
    job.error_message = error_message[:500]
    job.finished_at = utc_now()
    _append_job_event(db, job, "error", job.progress, error_message[:500])
    db.commit()

def _latest_assessment_run(db: Session, answer_id: str) -> AssessmentRun | None:
    return db.scalar(
        select(AssessmentRun)
        .where(AssessmentRun.answer_id == answer_id)
        .order_by(AssessmentRun.attempt_number.desc(), AssessmentRun.created_at.desc())
    )

def _persist_rubric_result(db: Session, run: AssessmentRun, result) -> None:
    for item in result.rubric_items:
        observation = RubricObservation(
            id=str(uuid4()),
            assessment_run_id=run.id,
            answer_id=run.answer_id,
            question_id=run.question_id,
            rubric_id=item.rubric_id,
            rubric_version=run.rubric_version,
            level=item.level,
            evidence_start=item.evidence_start,
            evidence_end=item.evidence_end,
            quoted_text=item.quoted_text,
            answer_text_hash=item.answer_text_hash,
            confidence=item.confidence,
            validity=item.validity,
            invalid_reason=item.invalid_reason,
        )
        db.add(observation)
        db.flush()
        db.add(
            EvidenceSpan(
                id=str(uuid4()),
                observation_id=observation.id,
                answer_id=run.answer_id,
                start_offset=item.evidence_start,
                end_offset=item.evidence_end,
                quoted_text=item.quoted_text,
                answer_text_hash=item.answer_text_hash,
                validity=item.validity,
                invalid_reason=item.invalid_reason,
            )
        )

def _answer_result_response(
    answer: AnswerAttempt,
    run: AssessmentRun | None,
    db: Session,
) -> dict:
    return {
        "answer": _answer_response(answer),
        "assessment": _assessment_response(run, db),
    }


def _answer_response(answer: AnswerAttempt) -> dict:
    return {
        "id": answer.id,
        "question_id": answer.question_id,
        "status": answer.status,
        "answer_text": answer.answer_text,
        "client_submission_id": answer.client_submission_id,
    }


def _assessment_response(run: AssessmentRun | None, db: Session) -> dict | None:
    if run is None:
        return None
    items = list(
        db.scalars(
            select(RubricObservation)
            .where(RubricObservation.assessment_run_id == run.id)
            .order_by(RubricObservation.rubric_id)
        )
    )
    return {
        "status": run.status,
        "evaluator": run.evaluator,
        "level": run.aggregate_level,
        "confidence": run.aggregate_confidence,
        "error_code": run.error_code,
        "error_reason": run.error_reason,
        "rubric_items": [
            {
                "rubric_id": item.rubric_id,
                "level": item.level,
                "evidence_start": item.evidence_start,
                "evidence_end": item.evidence_end,
                "quoted_text": item.quoted_text,
                "confidence": item.confidence,
                "validity": item.validity,
                "invalid_reason": item.invalid_reason,
            }
            for item in items
        ],
    }
