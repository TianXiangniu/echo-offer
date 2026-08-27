import hashlib
import json
from pathlib import Path
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import LOCAL_USER_ID, WORKFLOW_VERSION
from .models import (
    AnswerAttempt,
    AssessmentObservation,
    InterviewQuestion,
    InterviewSession,
    InterviewTarget,
    Resume,
    ResumeSource,
    ResumeProject,
    User,
)
from .providers import AssessmentProvider
from .question_bank import QuestionSpec
from .resume_files import (
    StoredResumeFile,
    ValidatedResumeFile,
    store_resume_file,
    validate_resume_upload,
)
from .resume_parsers import ResumeParserRegistry
from .schemas import AnswerSubmission, ProfileCreate


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


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _signals_from_json(value: str) -> tuple[str, ...]:
    return tuple(json.loads(value))


def _question_spec(question: InterviewQuestion) -> QuestionSpec:
    return QuestionSpec(
        order=question.order,
        category=question.category,
        is_anchor=question.is_anchor,
        prompt=question.prompt,
        knowledge_point_id=question.knowledge_point_id,
        rubric_version=question.rubric_version,
        signals=_signals_from_json(question.signals_json),
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

    max_version = db.scalar(
        select(func.max(ResumeProject.project_version)).join(Resume).where(Resume.user_id == user.id)
    )
    project = ResumeProject(
        id=str(uuid4()),
        resume_id=resume.id,
        project_version=(max_version or 0) + 1,
        **payload.project.model_dump(),
    )
    db.add(project)

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


def create_session(db: Session, profile_id: str, question_specs: list[QuestionSpec]) -> dict:
    project = db.get(ResumeProject, profile_id)
    if project is None:
        raise NotFoundError("profile not found")
    resume = db.get(Resume, project.resume_id)
    if resume is None:
        raise NotFoundError("resume not found")
    target = db.scalar(select(InterviewTarget).where(InterviewTarget.user_id == resume.user_id))
    if target is None:
        raise NotFoundError("interview target not found")

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
        observation = db.scalar(
            select(AssessmentObservation).where(AssessmentObservation.answer_id == existing.id)
        )
        return {"answer": _answer_response(existing), "observation": _observation_response(observation)}

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

    observation = None
    if payload.status != "skipped":
        result = assessment_provider.assess(_question_spec(question), payload.answer_text, payload.status)
        observation = AssessmentObservation(
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
        db.add(observation)

    session.current_question_index = min(session.total_questions, session.current_question_index + 1)
    session.session_version += 1
    if session.current_question_index >= session.total_questions:
        session.status = "completed"
    db.commit()
    return {"answer": _answer_response(answer), "observation": _observation_response(observation)}


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
    observations = list(
        db.scalars(
            select(AssessmentObservation).where(
                AssessmentObservation.question_id.in_([question.id for question in questions]),
                AssessmentObservation.validity == "valid",
            )
        )
    )
    by_question = {question.id: question for question in questions}
    completed = len({answer.question_id for answer in answers})
    anchor_ids = {question.id for question in questions if question.is_anchor}
    anchor_answered = len({answer.question_id for answer in answers if answer.question_id in anchor_ids})
    strengths = []
    gaps = []
    distribution = {str(level): 0 for level in range(5)}
    for observation in observations:
        distribution[str(observation.level)] += 1
        item = {
            "knowledge_point_id": by_question[observation.question_id].knowledge_point_id,
            "level": observation.level,
            "confidence": observation.confidence,
            "evidence": observation.quoted_text,
        }
        if observation.level >= 3:
            strengths.append(item)
        else:
            gaps.append(item)
    strengths.sort(key=lambda item: item["level"], reverse=True)
    gaps.sort(key=lambda item: item["level"])
    average_confidence = round(
        sum(observation.confidence for observation in observations) / len(observations), 2
    ) if observations else 0.0
    return {
        "session_id": session_id,
        "completion": {"completed": completed, "total": len(questions)},
        "coverage": round(completed / len(questions), 3) if questions else 0.0,
        "anchor_coverage": {"answered": anchor_answered, "total": len(anchor_ids)},
        "strengths": strengths[:3],
        "gaps": gaps[:3],
        "level_distribution": distribution,
        "valid_evidence_count": len(observations),
        "confidence": average_confidence,
        "evaluator": "alpha-local-rule-v1",
    }
