"""Follow-up question flow: decide, answer, and expose follow-up state.

每个题目最多一次追问（round=1），全场追问预算由程序侧硬约束，
模型只负责"是否追问 + 追问什么"，预算与幂等都在这里强制执行。
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnswerAttempt,
    InterviewFollowup,
    InterviewQuestion,
    InterviewSession,
    ResumeProject,
    ResumeProjectAnalysis,
    utc_now,
)
from .providers import FollowupDecisionProvider
from .rubrics import build_rubric
from .schemas import FollowupAnswerSubmission
from .workflow_common import (
    ConflictError,
    InvalidAnswerError,
    NotFoundError,
    _get_active_session,
    _hash_payload,
    _question_spec,
)

FOLLOWUP_SESSION_BUDGET = 4
FOLLOWUP_MAX_ROUNDS = 2
FOLLOWUP_ROUND = 1
FOLLOWUP_ANSWER_MAX_CHARS = 8000


def _followup_response(followup: InterviewFollowup) -> dict:
    return {
        "id": followup.id,
        "question_id": followup.question_id,
        "question_text": followup.question_text,
        "decision_reason": followup.decision_reason,
        "status": followup.status,
        "answer_text": followup.answer_text,
    }


def _get_question(db: Session, session_id: str, question_id: str) -> InterviewQuestion:
    question = db.scalar(
        select(InterviewQuestion).where(
            InterviewQuestion.id == question_id,
            InterviewQuestion.session_id == session_id,
        )
    )
    if question is None:
        raise NotFoundError("question not found")
    return question


def _get_primary_answer(db: Session, question_id: str) -> AnswerAttempt | None:
    return db.scalar(
        select(AnswerAttempt).where(
            AnswerAttempt.question_id == question_id,
            AnswerAttempt.primary_attempt_kind == "primary",
        )
    )


def _prepared_followups(db: Session, session: InterviewSession, question: InterviewQuestion) -> tuple[str, ...]:
    """预备追问来自 AI 项目分析的 question_chain，按题面匹配；匹配不到就为空。"""
    if not question.knowledge_point_id.startswith("project."):
        return ()
    project = db.get(ResumeProject, session.resume_project_id)
    if project is None or not project.analysis_id:
        return ()
    analysis = db.get(ResumeProjectAnalysis, project.analysis_id)
    if analysis is None:
        return ()
    chain = json.loads(analysis.analysis_json).get("question_chain", [])
    for item in chain:
        if not isinstance(item, dict) or item.get("prompt") != question.prompt:
            continue
        candidates = (
            item.get("followup_if_incomplete", "") or "",
            item.get("followup_if_conflicting", "") or "",
        )
        return tuple(candidate for candidate in candidates if candidate)
    return ()


def _waive_followup(
    db: Session,
    session: InterviewSession,
    question: InterviewQuestion,
    round_number: int,
) -> InterviewFollowup:
    waived = InterviewFollowup(
        id=str(uuid4()),
        session_id=session.id,
        question_id=question.id,
        round=round_number,
        question_text="",
        decision_reason="",
        status="waived",
    )
    db.add(waived)
    db.commit()
    return waived


def _question_followups(db: Session, question_id: str) -> list[InterviewFollowup]:
    rows = db.scalars(
        select(InterviewFollowup)
        .where(InterviewFollowup.question_id == question_id)
        .order_by(InterviewFollowup.round)
    )
    return list(rows)


def decide_followup(
    db: Session,
    session_id: str,
    question_id: str,
    provider: FollowupDecisionProvider | None,
    persona: str = "standard",
) -> dict:
    if provider is None or not hasattr(provider, "decide_followup"):
        from .providers import AssessmentProviderError

        raise AssessmentProviderError("provider_not_configured", "追问服务尚未配置")
    session = _get_active_session(db, session_id)
    question = _get_question(db, session_id, question_id)
    followups = _question_followups(db, question_id)
    pending = next((f for f in followups if f.status == "pending"), None)
    if pending is not None:
        return {"followup": _followup_response(pending)}

    answered = [f for f in followups if f.status == "answered"]
    next_round = len(answered) + 1
    primary = _get_primary_answer(db, question_id)
    budget_remaining = FOLLOWUP_SESSION_BUDGET - session.followup_budget_used
    if (
        primary is None
        or primary.status != "submitted"
        or len(answered) >= FOLLOWUP_MAX_ROUNDS
        or budget_remaining <= 0
    ):
        if any(f.round == next_round for f in followups):
            return {"followup": None}
        _waive_followup(db, session, question, next_round)
        return {"followup": None}

    rubric_items = [
        {"rubric_id": item.rubric_id, "criterion": item.criterion}
        for item in build_rubric(_question_spec(question)).items
    ]
    decision = provider.decide_followup(
        question.prompt,
        rubric_items,
        primary.answer_text,
        _prepared_followups(db, session, question),
        previous_followups=[
            {"question": f.question_text, "answer": f.answer_text or ""} for f in answered
        ],
        persona=persona,
    )
    if not decision.should_followup:
        _waive_followup(db, session, question, next_round)
        return {"followup": None}

    followup = InterviewFollowup(
        id=str(uuid4()),
        session_id=session.id,
        question_id=question_id,
        round=next_round,
        question_text=decision.followup_question,
        decision_reason=decision.reason,
        status="pending",
    )
    session.followup_budget_used += 1
    db.add(followup)
    db.commit()
    return {"followup": _followup_response(followup)}


def submit_followup_answer(
    db: Session,
    session_id: str,
    question_id: str,
    payload: FollowupAnswerSubmission,
) -> dict:
    _get_active_session(db, session_id)
    followup = db.scalar(
        select(InterviewFollowup).where(
            InterviewFollowup.question_id == question_id,
            InterviewFollowup.status == "pending",
        )
    )
    if followup is None:
        # 没有待答追问时定位最近一条已答追问，让重复提交走幂等/冲突路径
        followup = db.scalar(
            select(InterviewFollowup)
            .where(
                InterviewFollowup.question_id == question_id,
                InterviewFollowup.status == "answered",
            )
            .order_by(InterviewFollowup.round.desc())
        )
    if followup is None:
        raise NotFoundError("followup not found")

    payload_hash = _hash_payload(payload.model_dump())
    if followup.status == "answered":
        if (
            followup.client_submission_id == payload.client_submission_id
            and followup.payload_hash == payload_hash
        ):
            return {"followup": _followup_response(followup)}
        raise ConflictError("追问回答已提交且不可修改")
    if not payload.answer_text.strip():
        raise InvalidAnswerError("answer_text cannot be blank for submitted status")
    if len(payload.answer_text) > FOLLOWUP_ANSWER_MAX_CHARS:
        raise InvalidAnswerError("追问回答超出长度上限")

    followup.answer_text = payload.answer_text
    followup.answer_text_hash = hashlib.sha256(
        payload.answer_text.encode("utf-8")
    ).hexdigest()
    followup.client_submission_id = payload.client_submission_id
    followup.payload_hash = payload_hash
    followup.status = "answered"
    followup.answered_at = utc_now()
    db.commit()
    return {"followup": _followup_response(followup)}


def answered_followups_by_question(db: Session, session_id: str) -> dict[str, list[InterviewFollowup]]:
    followups = db.scalars(
        select(InterviewFollowup)
        .where(
            InterviewFollowup.session_id == session_id,
            InterviewFollowup.status == "answered",
        )
        .order_by(InterviewFollowup.round)
    )
    grouped: dict[str, list[InterviewFollowup]] = {}
    for followup in followups:
        grouped.setdefault(followup.question_id, []).append(followup)
    return grouped


def followups_for_session(db: Session, session_id: str) -> dict[str, InterviewFollowup]:
    """每题取一条用于展示：pending 优先，其次最新已答；waived 只作幂等记账不展示。"""
    followups = db.scalars(
        select(InterviewFollowup)
        .where(InterviewFollowup.session_id == session_id)
        .order_by(InterviewFollowup.round)
    )
    grouped: dict[str, list[InterviewFollowup]] = {}
    for followup in followups:
        grouped.setdefault(followup.question_id, []).append(followup)
    result: dict[str, InterviewFollowup] = {}
    for question_id, rows in grouped.items():
        pending = next((f for f in rows if f.status == "pending"), None)
        answered = [f for f in rows if f.status == "answered"]
        chosen = pending or (answered[-1] if answered else None)
        if chosen is not None:
            result[question_id] = chosen
    return result
