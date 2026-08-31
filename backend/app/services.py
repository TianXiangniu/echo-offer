import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import (
    LOCAL_USER_ID,
    MAX_ANALYSIS_RESUME_CHARS,
    SILICONFLOW_MODEL,
    WORKFLOW_VERSION,
)
from .models import (
    AnswerAttempt,
    AssessmentRun,
    AssessmentObservation,
    InterviewQuestion,
    InterviewSession,
    InterviewTarget,
    Resume,
    ResumeSource,
    ResumeProject,
    ResumeProjectAnalysis,
    ResumeProjectQuestion,
    RubricObservation,
    User,
)
from .assessment_engine import (
    AssessmentResponseError,
    build_explicit_unknown_assessment,
)
from .project_analysis import validate_analysis_evidence
from .providers import (
    AssessmentProvider,
    AssessmentProviderError,
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


def get_session_view(db: Session, session_id: str) -> dict:
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
    assessment_provider: AssessmentProvider,
) -> dict:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise NotFoundError("session not found")
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
        run = _latest_assessment_run(db, existing.id)
        if (
            existing.status != "skipped"
            and run is not None
            and run.status in {"pending", "invalid", "rejected"}
        ):
            run = evaluate_answer(db, existing, question, assessment_provider)
        observation = db.scalar(
            select(AssessmentObservation).where(AssessmentObservation.answer_id == existing.id)
        )
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

    run = None
    observation = None
    if payload.status != "skipped":
        run = evaluate_answer(db, answer, question, assessment_provider, payload.status)
        observation = db.scalar(
            select(AssessmentObservation).where(AssessmentObservation.answer_id == answer.id)
        )

    session.current_question_index = min(session.total_questions, session.current_question_index + 1)
    session.session_version += 1
    if session.current_question_index >= session.total_questions:
        session.status = "completed"
    db.commit()
    return _answer_result_response(answer, observation, run, db)


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
        db.add(
            RubricObservation(
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


def get_report(db: Session, session_id: str) -> dict:
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
    runs = list(
        db.scalars(
            select(AssessmentRun)
            .where(AssessmentRun.answer_id.in_(answer_ids))
            .order_by(AssessmentRun.attempt_number, AssessmentRun.created_at)
        )
    ) if answer_ids else []
    latest_runs: dict[str, AssessmentRun] = {}
    for run in runs:
        latest_runs[run.answer_id] = run

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
