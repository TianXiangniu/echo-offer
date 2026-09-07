import hashlib
import json
import math
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    InterviewQuestion,
    InterviewSession,
    OperationJob,
    OperationJobEvent,
    utc_now,
)
from .question_bank import QuestionSpec
from .rubrics import rubric_from_dict


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


def _recent_template_ids(db: Session, user_id: str, look_back_sessions: int = 3) -> set[str]:
    """近 N 场会话用过的题目模板，抽题时优先避开，保证练习不重复。"""
    recent_session_ids = list(
        db.scalars(
            select(InterviewSession.id)
            .where(
                InterviewSession.user_id == user_id,
                InterviewSession.archived_at.is_(None),
            )
            .order_by(InterviewSession.created_at.desc())
            .limit(look_back_sessions)
        )
    )
    if not recent_session_ids:
        return set()
    rows = db.execute(
        select(InterviewQuestion.template_id).where(
            InterviewQuestion.session_id.in_(recent_session_ids),
            InterviewQuestion.template_id.is_not(None),
        )
    )
    return {row[0] for row in rows if row[0]}


def _question_spec(question: InterviewQuestion) -> QuestionSpec:
    payload = json.loads(question.rubric_json or "{}")
    rubric_snapshot = rubric_from_dict(payload) if payload else None
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


def _get_active_session(db: Session, session_id: str) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    return session


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


def calculate_score_100(
    question_scores: dict[str, float],
    *,
    total_questions: int,
    completed_question_ids: set[str],
    expected_scored_question_ids: set[str],
) -> int | None:
    """Return a deterministic interview score, or None until it is complete."""
    if total_questions <= 0 or len(completed_question_ids) != total_questions:
        return None
    if not expected_scored_question_ids:
        return None
    if set(question_scores) != expected_scored_question_ids:
        return None

    average = sum(question_scores.values()) / len(question_scores)
    return min(100, max(0, math.floor(average + 0.5)))
