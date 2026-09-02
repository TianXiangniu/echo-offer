import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import timezone
from pathlib import Path
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import (
    ASSESSMENT_CASE_BATCH_SIZE,
    ASSESSMENT_JOB_LEASE_SECONDS,
    LOCAL_USER_ID,
    MAX_ANALYSIS_RESUME_CHARS,
    SILICONFLOW_MODEL,
    WORKFLOW_VERSION,
)
from .models import (
    AnswerAttempt,
    AssessmentBatch,
    AssessmentRun,
    AssessmentObservation,
    CandidateKnowledgeState,
    CandidateProfile,
    EvidenceSpan,
    InterviewQuestion,
    InterviewReport,
    InterviewSession,
    InterviewTarget,
    LearningRecommendation,
    OperationJob,
    OperationJobEvent,
    ProfileSnapshot,
    Resume,
    ResumeSource,
    ResumeProject,
    ResumeProjectAnalysis,
    ResumeProjectQuestion,
    RoleSkillRequirement,
    RubricObservation,
    SkillCatalog,
    User,
    utc_now,
)
from .assessment_engine import (
    AssessmentResponseError,
    build_explicit_unknown_assessment,
)
from .project_analysis import validate_analysis_evidence
from .profile_engine import (
    get_or_create_candidate_profile,
    update_candidate_profile,
)
from .providers import (
    AssessmentProvider,
    AssessmentProviderError,
    BatchAssessmentCase,
    ProjectAnalysisProvider,
    ProjectAnalysisProviderError,
)
from .question_bank import ProjectQuestionData, QuestionSpec, build_question_specs
from .rubrics import build_rubric, rubric_from_dict, rubric_to_dict
from .resume_files import (
    StoredResumeFile,
    ValidatedResumeFile,
    store_resume_file,
    validate_resume_upload,
)
from .resume_parsers import ResumeParserRegistry
from .schemas import AnswerSubmission, ProfileCreate
from .sse import format_sse_event


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class InvalidAnswerError(Exception):
    pass


class ResumeNotFoundError(Exception):
    code = "resume_not_found"


class ResumeOwnerConflictError(Exception):
    code = "resume_owner_conflict"


class ProjectAnalysisError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reconcile_confirmed_analysis_snapshot(
    analysis_json: str,
    confirmed_project: dict,
) -> str:
    try:
        snapshot = json.loads(analysis_json) if analysis_json else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    project_snapshot = snapshot.get("project")
    if not isinstance(project_snapshot, dict):
        project_snapshot = {}

    project_snapshot["core"] = dict(confirmed_project)
    snapshot["project"] = project_snapshot
    if not snapshot.get("schema_version"):
        snapshot["schema_version"] = "project-analysis-v2"
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)


def _append_job_event(
    db: Session,
    job: OperationJob,
    event_type: str,
    progress: int,
    message: str,
) -> None:
    last_sequence = db.scalar(
        select(func.max(OperationJobEvent.sequence)).where(
            OperationJobEvent.job_id == job.id
        )
    )
    db.add(
        OperationJobEvent(
            id=str(uuid4()),
            job_id=job.id,
            sequence=(last_sequence or 0) + 1,
            event_type=event_type,
            progress=progress,
            message=message,
        )
    )


def _create_batch_job(
    db: Session,
    session: InterviewSession,
    answers: list[AnswerAttempt],
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
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            age_seconds = (utc_now() - reference_time).total_seconds()
            if age_seconds > ASSESSMENT_JOB_LEASE_SECONDS:
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


def _signals_from_json(value: str) -> tuple[str, ...]:
    return tuple(json.loads(value))


def _question_spec(question: InterviewQuestion) -> QuestionSpec:
    rubric_snapshot = None
    try:
        payload = json.loads(question.rubric_json or "{}")
        if payload:
            rubric_snapshot = rubric_from_dict(payload)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        rubric_snapshot = None
    return QuestionSpec(
        order=question.order,
        category=question.category,
        is_anchor=question.is_anchor,
        prompt=question.prompt,
        knowledge_point_id=question.knowledge_point_id,
        rubric_version=question.rubric_version,
        signals=_signals_from_json(question.signals_json),
        rubric_snapshot=rubric_snapshot,
    )


def create_profile(db: Session, payload: ProfileCreate) -> dict:
    user = db.get(User, LOCAL_USER_ID)
    if user is None:
        user = User(id=LOCAL_USER_ID)
        db.add(user)
        db.flush()

    resume_text_hash = hashlib.sha256(payload.resume_text.encode("utf-8")).hexdigest()
    if payload.resume_id is None:
        resume = Resume(
            id=str(uuid4()),
            user_id=user.id,
            resume_text=payload.resume_text,
            text_hash=resume_text_hash,
        )
        db.add(resume)
        db.flush()
    else:
        resume = db.get(Resume, payload.resume_id)
        if resume is None:
            raise ResumeNotFoundError("resume not found")
        if resume.user_id != user.id:
            raise ResumeOwnerConflictError("resume does not belong to the current user")
        resume.resume_text = payload.resume_text
        resume.text_hash = resume_text_hash

    analysis = None
    if payload.analysis_id is not None:
        analysis = db.get(ResumeProjectAnalysis, payload.analysis_id)
        if analysis is None:
            raise NotFoundError("project analysis not found")
        if analysis.user_id != user.id or analysis.resume_id != resume.id:
            raise ConflictError("project analysis does not belong to the resume")
        if analysis.status != "draft":
            raise ConflictError("project analysis is not a draft")
        if payload.project_questions is None or len(payload.project_questions) != 3:
            raise ConflictError("exactly three project questions are required")
    elif payload.project_questions is not None:
        raise ConflictError("project_questions require analysis_id")

    max_version = db.scalar(
        select(func.max(ResumeProject.project_version)).join(Resume).where(Resume.user_id == user.id)
    )
    project = ResumeProject(
        id=str(uuid4()),
        resume_id=resume.id,
        project_version=(max_version or 0) + 1,
        analysis_id=analysis.id if analysis else None,
        **payload.project.model_dump(),
    )
    db.add(project)
    db.flush()

    if analysis is not None:
        original_questions = json.loads(analysis.analysis_json).get("questions", [])
        for index, question in enumerate(payload.project_questions or [], start=1):
            source = (
                "model"
                if index <= len(original_questions)
                and question.model_dump() == original_questions[index - 1]
                else "user_edited"
            )
            db.add(
                ResumeProjectQuestion(
                    id=str(uuid4()),
                    resume_project_id=project.id,
                    order=index,
                    prompt=question.prompt,
                    knowledge_point_id=question.knowledge_point_id,
                    signals_json=json.dumps(question.signals, ensure_ascii=False),
                    source=source,
                )
            )
        analysis.analysis_json = _reconcile_confirmed_analysis_snapshot(
            analysis.analysis_json,
            payload.project.model_dump(),
        )
        analysis.status = "confirmed"

    target = InterviewTarget(
        id=str(uuid4()),
        user_id=user.id,
        direction="agent_application_rag",
        level="one_to_three_years",
        language="zh_cn",
        company_type="unspecified",
        target_title="Agent 应用工程师",
        jd_text="",
    )
    db.add(target)
    db.commit()
    return {
        "profile_id": project.id,
        "user_id": user.id,
        "project_version": project.project_version,
        "resume_text_hash": resume_text_hash,
        "direction": target.direction,
        "level": target.level,
        "language": target.language,
    }


def parse_and_store_resume(
    db: Session,
    *,
    file_bytes: bytes,
    original_filename: str,
    content_type: str | None,
    upload_root: Path,
) -> dict:
    validated: ValidatedResumeFile = validate_resume_upload(
        original_filename, content_type, file_bytes
    )
    parser = ResumeParserRegistry.for_file(original_filename, content_type)
    parsed = parser.parse(file_bytes, original_filename, content_type)

    user = db.get(User, LOCAL_USER_ID)
    if user is None:
        user = User(id=LOCAL_USER_ID)
        db.add(user)
        db.flush()

    stored: StoredResumeFile | None = None
    try:
        stored = store_resume_file(file_bytes, validated.source_type, upload_root)
        resume = Resume(
            id=str(uuid4()),
            user_id=user.id,
            resume_text=parsed.text,
            text_hash=hashlib.sha256(parsed.text.encode("utf-8")).hexdigest(),
        )
        db.add(resume)
        db.flush()
        db.add(
            ResumeSource(
                id=str(uuid4()),
                resume_id=resume.id,
                source_type=parsed.source_type,
                original_filename=validated.original_filename,
                stored_path=str(stored.relative_path),
                file_size=len(file_bytes),
                file_hash=stored.file_hash,
                unit_count=parsed.unit_count,
                extracted_text=parsed.text,
                parse_status="parsed",
                warnings_json=json.dumps(parsed.warnings, ensure_ascii=False),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        if stored is not None:
            (upload_root / stored.relative_path).unlink(missing_ok=True)
        raise

    return {
        "resume_id": resume.id,
        "source_type": parsed.source_type,
        "original_filename": validated.original_filename,
        "unit_count": parsed.unit_count,
        "character_count": len(parsed.text),
        "extracted_text": parsed.text,
        "warnings": parsed.warnings,
    }


def analyze_resume_project(
    db: Session,
    provider: ProjectAnalysisProvider,
    resume_id: str,
    resume_text: str,
) -> dict:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise ResumeNotFoundError("resume not found")
    if resume.user_id != LOCAL_USER_ID:
        raise ResumeOwnerConflictError("resume does not belong to the current user")
    if not resume_text.strip():
        raise ProjectAnalysisError("resume_text_empty", "简历文本不能为空", 422)
    if len(resume_text) > MAX_ANALYSIS_RESUME_CHARS:
        raise ProjectAnalysisError("resume_text_too_long", "简历文本过长", 413)

    text_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()
    analysis = ResumeProjectAnalysis(
        id=str(uuid4()),
        resume_id=resume.id,
        user_id=resume.user_id,
        resume_text_hash=text_hash,
        model_name=SILICONFLOW_MODEL,
        provider_name="siliconflow",
        status="draft",
        analysis_json="{}",
    )
    db.add(analysis)
    try:
        result = provider.analyze(resume_text)
        result = validate_analysis_evidence(result, resume_text)
        analysis.analysis_json = json.dumps(
            result.model_dump(), ensure_ascii=False, sort_keys=True
        )
        db.commit()
    except ProjectAnalysisProviderError as exc:
        analysis.status = "failed"
        analysis.error_code = exc.code
        db.commit()
        raise
    except ValueError as exc:
        analysis.status = "failed"
        analysis.error_code = "invalid_model_response"
        db.commit()
        raise ProjectAnalysisError("invalid_model_response", "模型返回内容无法确认", 502) from exc

    return {
        "analysis_id": analysis.id,
        "resume_id": resume.id,
        "resume_text_hash": text_hash,
        "status": analysis.status,
        **result.model_dump(),
    }


async def stream_resume_project_analysis(
    db: Session,
    provider: ProjectAnalysisProvider,
    resume_id: str,
    resume_text: str,
    *,
    heartbeat_interval_seconds: float = 10.0,
) -> AsyncIterator[str]:
    resume = db.get(Resume, resume_id)
    if resume is None:
        yield format_sse_event(
            "error", {"code": "resume_not_found", "message": "resume not found"}
        )
        return
    if resume.user_id != LOCAL_USER_ID:
        yield format_sse_event(
            "error",
            {
                "code": "resume_owner_conflict",
                "message": "resume does not belong to the current user",
            },
        )
        return
    if not resume_text.strip():
        yield format_sse_event(
            "error", {"code": "resume_text_empty", "message": "简历文本不能为空"}
        )
        return
    if len(resume_text) > MAX_ANALYSIS_RESUME_CHARS:
        yield format_sse_event(
            "error", {"code": "resume_text_too_long", "message": "简历文本过长"}
        )
        return

    text_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()
    analysis = ResumeProjectAnalysis(
        id=str(uuid4()),
        resume_id=resume.id,
        user_id=resume.user_id,
        resume_text_hash=text_hash,
        model_name=SILICONFLOW_MODEL,
        provider_name="siliconflow",
        status="draft",
        analysis_json="{}",
    )
    db.add(analysis)
    db.flush()
    yield format_sse_event(
        "stage", {"stage": "received", "message": "已接收简历"}
    )
    yield format_sse_event(
        "stage", {"stage": "analyzing", "message": "正在分析项目"}
    )

    task = asyncio.create_task(asyncio.to_thread(provider.analyze, resume_text))
    try:
        while not task.done():
            finished, _ = await asyncio.wait(
                (task,), timeout=heartbeat_interval_seconds
            )
            if not finished:
                yield format_sse_event("heartbeat", {"stage": "analyzing"})

        result = task.result()
        yield format_sse_event(
            "stage", {"stage": "validating", "message": "正在校验证据"}
        )
        result = validate_analysis_evidence(result, resume_text)
        analysis.analysis_json = json.dumps(
            result.model_dump(), ensure_ascii=False, sort_keys=True
        )
        db.commit()
        response = {
            "analysis_id": analysis.id,
            "resume_id": resume.id,
            "resume_text_hash": text_hash,
            "status": analysis.status,
            **result.model_dump(),
        }
        yield format_sse_event(
            "stage", {"stage": "completed", "message": "分析完成"}
        )
        yield format_sse_event("result", response)
        yield format_sse_event("done", {"status": "completed"})
    except asyncio.CancelledError:
        task.cancel()
        raise
    except ProjectAnalysisProviderError as exc:
        analysis.status = "failed"
        analysis.error_code = exc.code
        db.commit()
        yield format_sse_event("error", {"code": exc.code, "message": str(exc)})
    except ValueError:
        analysis.status = "failed"
        analysis.error_code = "invalid_model_response"
        db.commit()
        yield format_sse_event(
            "error",
            {
                "code": "invalid_model_response",
                "message": "模型返回内容无法确认",
            },
        )


def create_session(
    db: Session,
    profile_id: str,
    question_specs: list[QuestionSpec] | None = None,
) -> dict:
    project = db.get(ResumeProject, profile_id)
    if project is None:
        raise NotFoundError("profile not found")
    resume = db.get(Resume, project.resume_id)
    if resume is None:
        raise NotFoundError("resume not found")
    target = db.scalar(select(InterviewTarget).where(InterviewTarget.user_id == resume.user_id))
    if target is None:
        raise NotFoundError("interview target not found")
    if question_specs is None:
        project_questions = list(
            db.scalars(
                select(ResumeProjectQuestion)
                .where(ResumeProjectQuestion.resume_project_id == project.id)
                .order_by(ResumeProjectQuestion.order)
            )
        )
        question_specs = build_question_specs(
            [
                ProjectQuestionData(
                    prompt=question.prompt,
                    knowledge_point_id=question.knowledge_point_id,
                    signals=_signals_from_json(question.signals_json),
                )
                for question in project_questions
            ]
            if project_questions
            else None
        )

    session = InterviewSession(
        id=str(uuid4()),
        user_id=resume.user_id,
        resume_project_id=project.id,
        target_id=target.id,
        profile_id=get_or_create_candidate_profile(
            db,
            user_id=resume.user_id,
            direction=target.direction,
            level=target.level,
            target_title=target.target_title,
        ).id,
        status="in_progress",
        current_question_index=0,
        total_questions=len(question_specs),
        workflow_version=WORKFLOW_VERSION,
        session_version=1,
    )
    db.add(session)
    db.flush()
    questions = []
    for spec in question_specs:
        question = InterviewQuestion(
            id=str(uuid4()),
            session_id=session.id,
            order=spec.order,
            category=spec.category,
            is_anchor=spec.is_anchor,
            prompt=spec.prompt,
            knowledge_point_id=spec.knowledge_point_id,
            rubric_version=spec.rubric_version,
            signals_json=json.dumps(spec.signals, ensure_ascii=False),
            rubric_json=json.dumps(rubric_to_dict(build_rubric(spec)), ensure_ascii=False),
        )
        db.add(question)
        questions.append(question)
    db.commit()
    return {"session_id": session.id, "status": session.status, "questions": questions}


def _question_response(question: InterviewQuestion) -> dict:
    return {
        "id": question.id,
        "order": question.order,
        "category": question.category,
        "is_anchor": question.is_anchor,
        "prompt": question.prompt,
        "knowledge_point_id": question.knowledge_point_id,
        "rubric_version": question.rubric_version,
    }


def _get_active_session(db: Session, session_id: str) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    return session


def get_session_view(db: Session, session_id: str) -> dict:
    session = _get_active_session(db, session_id)
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.order)
        )
    )
    answers = list(db.scalars(select(AnswerAttempt).where(AnswerAttempt.session_id == session_id)))
    answered_question_ids = {answer.question_id for answer in answers}
    current = next((question for question in questions if question.id not in answered_question_ids), None)
    completed = len(answered_question_ids)
    if completed == len(questions) and session.status != "completed":
        session.status = "completed"
        session.current_question_index = len(questions)
        db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "current_question": _question_response(current) if current else None,
        "questions": [
            {
                **_question_response(question),
                "answered": question.id in answered_question_ids,
            }
            for question in questions
        ],
        "progress": {"completed": completed, "total": len(questions)},
    }


def submit_answer(
    db: Session,
    session_id: str,
    payload: AnswerSubmission,
) -> dict:
    session = _get_active_session(db, session_id)
    question = db.scalar(
        select(InterviewQuestion).where(
            InterviewQuestion.id == payload.question_id,
            InterviewQuestion.session_id == session_id,
        )
    )
    if question is None:
        raise NotFoundError("question not found")
    if payload.status == "submitted" and not payload.answer_text.strip():
        raise InvalidAnswerError("answer_text cannot be blank for submitted status")

    payload_hash = _hash_payload(payload.model_dump())
    existing = db.scalar(
        select(AnswerAttempt).where(
            AnswerAttempt.session_id == session_id,
            AnswerAttempt.client_submission_id == payload.client_submission_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise ConflictError("client_submission_id was already used with different content")
        observation = db.scalar(
            select(AssessmentObservation).where(AssessmentObservation.answer_id == existing.id)
        )
        run = _latest_assessment_run(db, existing.id)
        return _answer_result_response(existing, observation, run, db)

    answer_text_hash = hashlib.sha256(payload.answer_text.encode("utf-8")).hexdigest()
    answer = AnswerAttempt(
        id=str(uuid4()),
        session_id=session_id,
        question_id=question.id,
        client_submission_id=payload.client_submission_id,
        primary_attempt_kind="primary",
        status=payload.status,
        answer_text=payload.answer_text,
        answer_text_hash=answer_text_hash,
        payload_hash=payload_hash,
    )
    db.add(answer)
    db.commit()

    session.current_question_index = min(session.total_questions, session.current_question_index + 1)
    session.session_version += 1
    if session.current_question_index >= session.total_questions:
        session.status = "completed"
    db.commit()
    return _answer_result_response(answer, None, None, db)


def _batch_status(runs: list[AssessmentRun]) -> str:
    statuses = {run.status for run in runs}
    if "pending" in statuses:
        return "pending"
    if "rejected" in statuses:
        return "rejected"
    if "invalid" in statuses:
        return "invalid"
    return "valid"


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


def assess_session(
    db: Session,
    session_id: str,
    assessment_provider: AssessmentProvider,
) -> dict:
    """Evaluate all completed answers with one provider call."""
    session = _get_active_session(db, session_id)
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.order)
        )
    )
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
                    update_candidate_profile(db, session_id, commit=False)
                db.commit()
            except Exception:
                db.rollback()
                raise
        return _batch_result_response(db, answers, len(questions), batch_id)
    if not scored_answers:
        return _batch_result_response(db, answers, len(questions), None)

    question_by_id = {question.id: question for question in questions}
    answers_to_evaluate = [
        answer
        for answer in scored_answers
        if existing_runs[answer.id] is None or existing_runs[answer.id].status != "valid"
    ]
    evaluator = getattr(assessment_provider, "evaluator", "siliconflow-blind-rubric-v1")
    batch_id = str(uuid4())
    job = _create_batch_job(db, session, scored_answers)
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
        else:
            cases.append(
                BatchAssessmentCase(
                    answer_id=answer.id,
                    question_id=question.id,
                    question=question_spec,
                    answer_text=answer.answer_text,
                )
            )
    db.commit()

    chunks = _split_assessment_cases(cases, ASSESSMENT_CASE_BATCH_SIZE)
    failed_chunks: list[tuple[str, str]] = []
    successful_case_count = sum(
        1 for answer in scored_answers if answer.status == "explicit_unknown"
    )

    for chunk_index, chunk in enumerate(chunks, start=1):
        try:
            results = assessment_provider.assess_batch(chunk)
            expected_keys = {(case.answer_id, case.question_id) for case in chunk}
            actual_keys = {(item.answer_id, item.question_id) for item in results}
            if actual_keys != expected_keys or len(results) != len(actual_keys):
                raise AssessmentResponseError("invalid_batch_case", "批量评分结果与回答不匹配")
            for item in results:
                run = runs_by_answer[item.answer_id]
                _persist_rubric_result(db, run, item.result)
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
            successful_case_count += len(chunk)
            db.commit()
            progress = 20 + int(70 * chunk_index / max(1, len(chunks)))
            job.progress = progress
            _append_job_event(db, job, "stage", progress, f"已完成 {chunk_index}/{len(chunks)} 批回答")
            db.commit()
        except AssessmentProviderError as exc:
            db.rollback()
            for case in chunk:
                run = runs_by_answer[case.answer_id]
                run.status = "pending"
                run.error_code = exc.code
                run.error_reason = str(exc)[:500]
            failed_chunks.append((exc.code, str(exc)))
            db.commit()
        except AssessmentResponseError as exc:
            db.rollback()
            for case in chunk:
                run = runs_by_answer[case.answer_id]
                run.status = "rejected"
                run.error_code = exc.code
                run.error_reason = str(exc)[:500]
            failed_chunks.append((exc.code, str(exc)))
            db.commit()
        except Exception as exc:
            db.rollback()
            for case in chunk:
                run = runs_by_answer[case.answer_id]
                run.status = "pending"
                run.error_code = "system_error"
                run.error_reason = str(exc)[:500]
            failed_chunks.append(("system_error", str(exc)))
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
                update_candidate_profile(db, session_id, commit=False)
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


def evaluate_answer(
    db: Session,
    answer: AnswerAttempt,
    question: InterviewQuestion,
    assessment_provider: AssessmentProvider,
    source_status: str | None = None,
) -> AssessmentRun:
    source_status = source_status or answer.status
    question_spec = _question_spec(question)
    rubric = build_rubric(question_spec)
    previous = _latest_assessment_run(db, answer.id)
    attempt_number = previous.attempt_number + 1 if previous is not None else 1
    evaluator = getattr(assessment_provider, "evaluator", "siliconflow-blind-rubric-v1")
    run = AssessmentRun(
        id=str(uuid4()),
        answer_id=answer.id,
        question_id=question.id,
        evaluator=evaluator,
        rubric_version=rubric.version,
        status="pending",
        attempt_number=attempt_number,
    )
    db.add(run)
    db.commit()

    try:
        if source_status == "explicit_unknown":
            result = build_explicit_unknown_assessment(
                question_spec,
                answer.answer_text,
                evaluator=evaluator,
            )
        else:
            result = assessment_provider.assess(
                question_spec,
                answer.answer_text,
                source_status,
            )
        _persist_rubric_result(db, run, result)
        if result.rubric_items and all(item.validity == "valid" for item in result.rubric_items):
            run.status = "valid"
            run.aggregate_level = result.level
            run.aggregate_confidence = result.confidence
            if source_status == "explicit_unknown":
                _persist_legacy_observation(db, answer, question, result)
        elif result.rubric_items:
            run.status = "invalid"
            run.error_code = "invalid_evidence"
            run.error_reason = "至少一个 Rubric 证据未通过完整性校验"
        else:
            _persist_legacy_observation(db, answer, question, result)
            run.status = "valid"
            run.aggregate_level = result.level
            run.aggregate_confidence = result.confidence
        db.commit()
    except AssessmentProviderError as exc:
        run.status = "pending"
        run.error_code = exc.code
        run.error_reason = str(exc)[:500]
        db.commit()
    except AssessmentResponseError as exc:
        run.status = "rejected"
        run.error_code = exc.code
        run.error_reason = str(exc)
        db.commit()
    except Exception as exc:
        run.status = "pending"
        run.error_code = "system_error"
        run.error_reason = str(exc)[:500]
        db.commit()
    return run


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


def _persist_legacy_observation(
    db: Session,
    answer: AnswerAttempt,
    question: InterviewQuestion,
    result,
) -> None:
    db.add(
        AssessmentObservation(
            id=str(uuid4()),
            answer_id=answer.id,
            question_id=question.id,
            level=result.level,
            evidence_start=result.evidence_start,
            evidence_end=result.evidence_end,
            quoted_text=result.quoted_text,
            answer_text_hash=result.answer_text_hash,
            gaps_json=json.dumps(result.gaps, ensure_ascii=False),
            confidence=result.confidence,
            validity="valid",
        )
    )


def _answer_result_response(
    answer: AnswerAttempt,
    observation: AssessmentObservation | None,
    run: AssessmentRun | None,
    db: Session,
) -> dict:
    return {
        "answer": _answer_response(answer),
        "observation": _observation_response(observation),
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


def _observation_response(observation: AssessmentObservation | None) -> dict | None:
    if observation is None:
        return None
    return {
        "id": observation.id,
        "level": observation.level,
        "evidence_start": observation.evidence_start,
        "evidence_end": observation.evidence_end,
        "quoted_text": observation.quoted_text,
        "confidence": observation.confidence,
        "gaps": json.loads(observation.gaps_json),
        "validity": observation.validity,
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


def _build_report_payload(
    db: Session,
    session_id: str,
    assessment_batch_id: str | None = None,
) -> dict:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise NotFoundError("session not found")
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.order)
        )
    )
    answers = list(db.scalars(select(AnswerAttempt).where(AnswerAttempt.session_id == session_id)))
    by_question = {question.id: question for question in questions}
    completed = len({answer.question_id for answer in answers})
    anchor_ids = {question.id for question in questions if question.is_anchor}
    anchor_answered = len({answer.question_id for answer in answers if answer.question_id in anchor_ids})
    answer_ids = [answer.id for answer in answers]
    run_query = (
        select(AssessmentRun)
        .where(AssessmentRun.answer_id.in_(answer_ids))
        .order_by(AssessmentRun.attempt_number, AssessmentRun.created_at)
    ) if answer_ids else None
    all_runs = list(db.scalars(run_query)) if run_query is not None else []
    latest_all_runs: dict[str, AssessmentRun] = {}
    for run in all_runs:
        latest_all_runs[run.answer_id] = run
    if assessment_batch_id:
        latest_runs: dict[str, AssessmentRun] = {}
        for run in all_runs:
            if run.assessment_batch_id == assessment_batch_id:
                latest_runs[run.answer_id] = run
        for answer_id, run in latest_all_runs.items():
            latest_runs.setdefault(answer_id, run)
    else:
        latest_runs = latest_all_runs

    status_counts = {status: 0 for status in ("pending", "valid", "invalid", "rejected")}
    for run in latest_runs.values():
        if run.status in status_counts:
            status_counts[run.status] += 1

    strengths = []
    gaps = []
    distribution = {str(level): 0 for level in range(5)}
    rubric_items = []
    report_observations = []
    legacy_observations = list(
        db.scalars(
            select(AssessmentObservation).where(
                AssessmentObservation.question_id.in_([question.id for question in questions]),
                AssessmentObservation.validity == "valid",
            )
        )
    ) if questions else []
    for answer in answers:
        run = latest_runs.get(answer.id)
        if run is not None:
            if run.status != "valid" or run.aggregate_level is None:
                continue
            evidence = db.scalar(
                select(RubricObservation)
                .where(
                    RubricObservation.assessment_run_id == run.id,
                    RubricObservation.validity == "valid",
                )
                .order_by(RubricObservation.confidence.desc())
            )
            valid_items = list(
                db.scalars(
                    select(RubricObservation)
                    .where(
                        RubricObservation.assessment_run_id == run.id,
                        RubricObservation.validity == "valid",
                    )
                    .order_by(RubricObservation.rubric_id)
                )
            )
            rubric_items.extend(
                {
                    "question_id": answer.question_id,
                    "knowledge_point_id": by_question[answer.question_id].knowledge_point_id,
                    "rubric_id": item.rubric_id,
                    "level": item.level,
                    "confidence": item.confidence,
                    "evidence": item.quoted_text,
                }
                for item in valid_items
            )
            legacy = next((item for item in legacy_observations if item.answer_id == answer.id), None)
            report_observations.append(
                {
                    "question_id": answer.question_id,
                    "level": run.aggregate_level,
                    "confidence": run.aggregate_confidence or 0.0,
                    "evidence": evidence.quoted_text if evidence else legacy.quoted_text if legacy else answer.answer_text,
                }
            )
        else:
            legacy = next((item for item in legacy_observations if item.answer_id == answer.id), None)
            if legacy is not None:
                report_observations.append(
                    {
                        "question_id": answer.question_id,
                        "level": legacy.level,
                        "confidence": legacy.confidence,
                        "evidence": legacy.quoted_text,
                    }
                )

    for observation in report_observations:
        distribution[str(observation["level"])] += 1
        item = {
            "knowledge_point_id": by_question[observation["question_id"]].knowledge_point_id,
            "level": observation["level"],
            "confidence": observation["confidence"],
            "evidence": observation["evidence"],
        }
        if observation["level"] >= 3:
            strengths.append(item)
        else:
            gaps.append(item)
    strengths.sort(key=lambda item: item["level"], reverse=True)
    gaps.sort(key=lambda item: item["level"])
    average_confidence = round(
        sum(observation["confidence"] for observation in report_observations)
        / len(report_observations),
        2,
    ) if report_observations else 0.0
    evaluators = {run.evaluator for run in latest_runs.values()}
    if not evaluators and report_observations:
        evaluators.add("alpha-local-rule-v1")
    evaluator = next(iter(evaluators)) if len(evaluators) == 1 else "mixed"
    return {
        "session_id": session_id,
        "completion": {"completed": completed, "total": len(questions)},
        "coverage": round(completed / len(questions), 3) if questions else 0.0,
        "anchor_coverage": {"answered": anchor_answered, "total": len(anchor_ids)},
        "strengths": strengths[:3],
        "gaps": gaps[:3],
        "level_distribution": distribution,
        "valid_evidence_count": len(report_observations),
        "confidence": average_confidence,
        "evaluator": evaluator,
        "assessment_status_counts": status_counts,
        "rubric_items": rubric_items,
    }


def persist_interview_report(
    db: Session,
    session_id: str,
    *,
    assessment_batch_id: str | None = None,
    status: str = "ready",
    commit: bool = True,
) -> InterviewReport:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise NotFoundError("session not found")
    latest_version = db.scalar(
        select(func.max(InterviewReport.version)).where(
            InterviewReport.session_id == session_id
        )
    )
    report_payload = _build_report_payload(
        db,
        session_id,
        assessment_batch_id=assessment_batch_id,
    )
    latest_run = db.scalar(
        select(AssessmentRun)
        .where(
            or_(
                AssessmentRun.assessment_batch_id == assessment_batch_id,
                AssessmentRun.batch_id == assessment_batch_id,
            )
        )
        .order_by(AssessmentRun.created_at.desc())
    ) if assessment_batch_id else None
    report = InterviewReport(
        id=str(uuid4()),
        session_id=session_id,
        assessment_run_id=latest_run.id if latest_run else None,
        assessment_batch_id=assessment_batch_id,
        version=(latest_version or 0) + 1,
        status=status,
        report_json=json.dumps(report_payload, ensure_ascii=False, sort_keys=True),
    )
    db.add(report)
    db.flush()
    session.current_report_id = report.id
    if latest_run is not None:
        session.current_assessment_run_id = latest_run.id
    session.current_assessment_batch_id = assessment_batch_id
    if commit:
        db.commit()
    return report


def get_persisted_report(db: Session, session_id: str) -> dict | None:
    report = db.scalar(
        select(InterviewReport)
        .where(
            InterviewReport.session_id == session_id,
            InterviewReport.status.in_(("ready", "partial")),
        )
        .order_by(InterviewReport.version.desc())
    )
    if report is None:
        return None
    return json.loads(report.report_json)


def get_report(db: Session, session_id: str) -> dict:
    _get_active_session(db, session_id)
    return get_persisted_report(db, session_id) or _build_report_payload(db, session_id)


def archive_interview(db: Session, session_id: str) -> None:
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    session.archived_at = utc_now()
    db.commit()


def list_interview_history(db: Session) -> list[dict]:
    sessions = list(
        db.scalars(
            select(InterviewSession)
            .where(InterviewSession.archived_at.is_(None))
            .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        )
    )
    history = []
    for session in sessions:
        question_count = db.scalar(
            select(func.count(InterviewQuestion.id)).where(
                InterviewQuestion.session_id == session.id
            )
        ) or 0
        answered_count = db.scalar(
            select(func.count(func.distinct(AnswerAttempt.question_id))).where(
                AnswerAttempt.session_id == session.id
            )
        ) or 0
        report = db.scalar(
            select(InterviewReport)
            .where(InterviewReport.session_id == session.id)
            .order_by(InterviewReport.version.desc())
        )
        job = db.scalar(
            select(OperationJob)
            .where(OperationJob.session_id == session.id)
            .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
        )
        target = db.get(InterviewTarget, session.target_id)
        project = db.get(ResumeProject, session.resume_project_id)
        report_payload = json.loads(report.report_json) if report else None
        history.append(
            {
                "session_id": session.id,
                "status": session.status,
                "profile_id": session.profile_id,
                "project_name": project.project_name if project else None,
                "direction": target.direction if target else None,
                "target_title": target.target_title if target else None,
                "completed": answered_count,
                "total": question_count,
                "report_status": report.status if report else None,
                "analysis_status": job.status if job else None,
                "strength_count": len(report_payload["strengths"]) if report_payload else None,
                "gap_count": len(report_payload["gaps"]) if report_payload else None,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
        )
    return history


def _recommendation_response(db: Session, recommendation: LearningRecommendation) -> dict:
    skill = db.get(SkillCatalog, recommendation.skill_id)
    return {
        "id": recommendation.id,
        "skill_id": recommendation.skill_id,
        "skill_name": skill.canonical_name if skill else recommendation.skill_id,
        "priority": recommendation.priority,
        "reason": recommendation.reason,
        "actions": json.loads(recommendation.actions_json),
        "success_criteria": json.loads(recommendation.success_criteria_json),
        "status": recommendation.status,
        "recommended_review_at": recommendation.recommended_review_at,
    }


def get_profile_summary(db: Session, profile_id: str) -> dict:
    profile = db.get(CandidateProfile, profile_id)
    if profile is None:
        raise NotFoundError("profile not found")
    states = list(
        db.scalars(
            select(CandidateKnowledgeState)
            .where(CandidateKnowledgeState.profile_id == profile.id)
            .order_by(CandidateKnowledgeState.current_level.asc())
        )
    )
    skills = []
    for state in states:
        skill = db.get(SkillCatalog, state.skill_id)
        requirement = db.scalar(
            select(RoleSkillRequirement).where(
                RoleSkillRequirement.direction == profile.direction,
                RoleSkillRequirement.level == profile.level,
                RoleSkillRequirement.skill_id == state.skill_id,
            )
        )
        skills.append(
            {
                "skill_id": state.skill_id,
                "skill_name": skill.canonical_name if skill else state.skill_id,
                "category": skill.category if skill else "其他",
                "level": state.current_level,
                "confidence": state.confidence,
                "sample_count": state.valid_sample_count,
                "trend": state.trend,
                "target_level": requirement.target_level if requirement else None,
                "last_session_id": state.last_session_id,
            }
        )
    recommendations = []
    if profile.current_snapshot_id:
        recommendations = [
            _recommendation_response(db, item)
            for item in db.scalars(
                select(LearningRecommendation)
                .where(
                    LearningRecommendation.profile_id == profile.id,
                    LearningRecommendation.profile_snapshot_id == profile.current_snapshot_id,
                )
            )
        ]
        priority_order = {"high": 0, "medium": 1, "insufficient_data": 2, "low": 3}
        recommendations.sort(key=lambda item: priority_order.get(item["priority"], 4))
    latest_state = max(
        (state for state in states if state.last_assessed_at is not None),
        key=lambda state: state.last_assessed_at,
        default=None,
    )
    last_session_id = latest_state.last_session_id if latest_state else None
    return {
        "profile_id": profile.id,
        "direction": profile.direction,
        "level": profile.level,
        "target_title": profile.target_title,
        "summary": profile.summary,
        "last_session_id": last_session_id,
        "skills": skills,
        "recommendations": recommendations,
        "updated_at": profile.updated_at,
    }


def get_profile_history(db: Session, profile_id: str) -> list[dict]:
    profile = db.get(CandidateProfile, profile_id)
    if profile is None:
        raise NotFoundError("profile not found")
    snapshots = list(
        db.scalars(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.profile_id == profile_id)
            .order_by(ProfileSnapshot.version.desc())
        )
    )
    return [
        {
            "id": snapshot.id,
            "profile_id": snapshot.profile_id,
            "source_session_id": snapshot.source_session_id,
            "version": snapshot.version,
            "profile": json.loads(snapshot.profile_json),
            "created_at": snapshot.created_at,
        }
        for snapshot in snapshots
    ]


def get_operation_job(db: Session, job_id: str) -> dict:
    job = db.get(OperationJob, job_id)
    if job is None:
        raise NotFoundError("operation job not found")
    events = list(
        db.scalars(
            select(OperationJobEvent)
            .where(OperationJobEvent.job_id == job.id)
            .order_by(OperationJobEvent.sequence)
        )
    )
    return {
        "id": job.id,
        "operation_kind": job.operation_kind,
        "session_id": job.session_id,
        "assessment_batch_id": job.assessment_batch_id,
        "status": job.status,
        "progress": job.progress,
        "current_stage": job.current_stage,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "progress": event.progress,
                "message": event.message,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


def update_recommendation_status(
    db: Session,
    recommendation_id: str,
    status: str,
) -> dict:
    if status not in {"recommended", "in_progress", "completed", "dismissed"}:
        raise InvalidAnswerError("unsupported recommendation status")
    recommendation = db.get(LearningRecommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("recommendation not found")
    recommendation.status = status
    db.commit()
    return _recommendation_response(db, recommendation)
