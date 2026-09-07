"""Per-question practice feedback.

练习反馈与盲评分严格隔离：反馈只存在独立表里，评分链路（assess_session）
不读取本模块的任何数据；反馈调用也禁止输出分数。
"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AnswerAttempt, InterviewQuestion, QuestionFeedback
from .workflow_common import ConflictError, NotFoundError


def _feedback_response(feedback: QuestionFeedback) -> dict:
    return {
        "question_id": feedback.question_id,
        "content": feedback.content,
        "focus_hints": json.loads(feedback.focus_hints_json),
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


def get_feedback(db: Session, question_id: str) -> QuestionFeedback | None:
    return db.scalar(
        select(QuestionFeedback).where(QuestionFeedback.question_id == question_id)
    )


def generate_feedback(
    db: Session,
    session_id: str,
    question_id: str,
    provider,
) -> dict:
    if provider is None or not hasattr(provider, "feedback_for_answer"):
        from .providers import AssessmentProviderError

        raise AssessmentProviderError("provider_not_configured", "练习反馈服务尚未配置")
    question = _get_question(db, session_id, question_id)
    existing = get_feedback(db, question_id)
    if existing is not None:
        # 首答不可变，因此已有反馈永远与回答一致，直接复用不重复调用模型。
        return {"feedback": _feedback_response(existing)}

    answer = db.scalar(
        select(AnswerAttempt).where(
            AnswerAttempt.question_id == question_id,
            AnswerAttempt.primary_attempt_kind == "primary",
        )
    )
    if answer is None:
        raise NotFoundError("answer not found")
    if answer.status != "submitted":
        raise ConflictError("该题没有可点评的正式回答")

    feedback = provider.feedback_for_answer(question.prompt, answer.answer_text)
    row = QuestionFeedback(
        id=str(uuid4()),
        session_id=session_id,
        question_id=question_id,
        content=feedback.content,
        focus_hints_json=json.dumps(feedback.focus_hints, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    return {"feedback": _feedback_response(row)}


def feedback_for_session(db: Session, session_id: str) -> dict[str, QuestionFeedback]:
    rows = db.scalars(
        select(QuestionFeedback).where(QuestionFeedback.session_id == session_id)
    )
    return {row.question_id: row for row in rows}
