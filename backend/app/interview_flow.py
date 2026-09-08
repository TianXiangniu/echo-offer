from __future__ import annotations

import hashlib
import json
import random
from dataclasses import replace
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assessment_flow import _answer_result_response, _latest_assessment_run
from .config import LOCAL_USER_ID, WORKFLOW_VERSION
from .followup_flow import followups_for_session
from .feedback_flow import feedback_for_session
from .dialog_flow import session_timeline
from .models import (
    AnswerAttempt,
    InterviewQuestion,
    InterviewSession,
    InterviewTarget,
    Resume,
    ResumeProject,
    ResumeProjectQuestion,
    User,
)
from .profile_engine import get_or_create_candidate_profile
from .question_bank import (
    ProjectQuestionData,
    QuestionSpec,
    build_foundation_specs,
    build_knowledge_specs,
    build_question_specs,
)
from .rubrics import build_rubric, rubric_to_dict
from .schemas import AnswerSubmission
from .interview_types import interview_type_from_mode
from .workflow_common import (
    ConflictError,
    InvalidAnswerError,
    NotFoundError,
    _get_active_session,
    _hash_payload,
    _recent_template_ids,
    _signals_from_json,
)

def _truncate_fact(value: str, limit: int = 150) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


_PROJECT_FACT_FIELDS: dict[str, tuple[str, ...]] = {
    "project.ownership_and_context": ("background_goal", "responsibilities"),
    "project.architecture_tradeoffs": ("core_solution", "engineering_challenges"),
    "project.evaluation_and_reproducibility": ("quantified_results", "failure_improvements"),
}


def _project_reference_facts(knowledge_point_id: str, project: ResumeProject) -> tuple[str, ...]:
    fields = _PROJECT_FACT_FIELDS.get(knowledge_point_id, ())
    facts = tuple(
        _truncate_fact(getattr(project, field, ""))
        for field in fields
        if _truncate_fact(getattr(project, field, ""))
    )
    return facts


def _persist_questions(
    db: Session,
    session: InterviewSession,
    specs: list[QuestionSpec],
) -> list[InterviewQuestion]:
    questions = []
    for spec in specs:
        question = InterviewQuestion(
            id=str(uuid4()),
            session_id=session.id,
            order=spec.order,
            category=spec.category,
            is_anchor=spec.is_anchor,
            prompt=spec.prompt,
            knowledge_point_id=spec.knowledge_point_id,
            template_id=spec.template_id or None,
            rubric_version=spec.rubric_version,
            signals_json=json.dumps(spec.signals, ensure_ascii=False),
            rubric_json=json.dumps(rubric_to_dict(build_rubric(spec)), ensure_ascii=False),
        )
        db.add(question)
        questions.append(question)
    return questions


def create_session(
    db: Session,
    profile_id: str,
    question_specs: list[QuestionSpec] | None = None,
    mode: str = "classic",
) -> dict:
    if mode == "graph" and question_specs is None:
        question_specs = []
    project = db.get(ResumeProject, profile_id)
    if project is None:
        raise NotFoundError("profile not found")
    resume = db.get(Resume, project.resume_id)
    if resume is None:
        raise NotFoundError("resume not found")
    target = db.scalar(select(InterviewTarget).where(InterviewTarget.user_id == resume.user_id))
    if target is None:
        raise NotFoundError("interview target not found")
    excluded_template_ids = _recent_template_ids(db, resume.user_id)
    rng = random.Random()
    if mode == "dialog" and question_specs is None:
        question_specs = build_knowledge_specs(
            excluded_template_ids=excluded_template_ids, rng=rng
        )
    elif question_specs is None:
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
                    reference_facts=_project_reference_facts(
                        question.knowledge_point_id, project
                    ),
                )
                for question in project_questions
            ]
            if project_questions
            else None,
            excluded_template_ids=excluded_template_ids,
            rng=rng,
        )
        if not project_questions:
            question_specs = [
                replace(
                    spec,
                    reference_facts=spec.reference_facts
                    or _project_reference_facts(spec.knowledge_point_id, project),
                )
                for spec in question_specs
            ]

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
        followup_budget_used=0,
        mode=mode,
        stage="intro" if mode == "dialog" else ("planning" if mode == "graph" else "knowledge"),
        workflow_version=WORKFLOW_VERSION,
        session_version=1,
    )
    db.add(session)
    db.flush()
    questions = _persist_questions(db, session, question_specs)
    if mode == "dialog":
        db.commit()
        from .dialog_flow import ensure_intro

        ensure_intro(db, session)
    elif mode == "graph":
        from .interview_graph_projection import project_graph_event

        project_graph_event(
            db,
            {
                "session_id": session.id,
                "graph_step_id": "session-created",
                "event_kind": "state_updated",
                "payload": {"stage": "planning", "current_question_index": 0},
            },
            commit=False,
        )
        db.commit()
    else:
        db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "interview_type": interview_type_from_mode(session.mode),
        "questions": questions,
    }


def create_foundation_session(db: Session) -> dict:
    """Create a five-question technical session without requiring a resume."""

    user = db.get(User, LOCAL_USER_ID)
    if user is None:
        user = User(id=LOCAL_USER_ID)
        db.add(user)
        db.flush()

    target = db.scalar(select(InterviewTarget).where(InterviewTarget.user_id == user.id))
    if target is None:
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
        db.flush()

    profile = get_or_create_candidate_profile(
        db,
        user_id=user.id,
        direction=target.direction,
        level=target.level,
        target_title=target.target_title,
    )
    specs = build_foundation_specs(
        excluded_template_ids=_recent_template_ids(db, user.id),
        rng=random.Random(),
    )
    session = InterviewSession(
        id=str(uuid4()),
        user_id=user.id,
        resume_project_id=None,
        target_id=target.id,
        profile_id=profile.id,
        status="in_progress",
        current_question_index=0,
        total_questions=len(specs),
        followup_budget_used=0,
        session_kind="foundation",
        mode="classic",
        stage="knowledge",
        workflow_version=WORKFLOW_VERSION,
        session_version=1,
    )
    db.add(session)
    db.flush()
    questions = _persist_questions(db, session, specs)
    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "interview_type": "foundation",
        "questions": questions,
    }

def _question_response(question: InterviewQuestion) -> dict:
    return {
        "id": question.id,
        "order": question.order,
        "category": question.category,
        "is_anchor": question.is_anchor,
        "prompt": question.prompt,
        "knowledge_point_id": question.knowledge_point_id,
        "template_id": question.template_id,
        "rubric_version": question.rubric_version,
    }

def get_session_view(
    db: Session,
    session_id: str,
    graph_state: dict | None = None,
) -> dict:
    session = _get_active_session(db, session_id)
    if session.mode == "graph":
        from .interview_graph_projection import graph_session_view

        return graph_session_view(db, session, graph_state)
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.order)
        )
    )
    answers = list(db.scalars(select(AnswerAttempt).where(AnswerAttempt.session_id == session_id)))
    answered_question_ids = {answer.question_id for answer in answers}
    followups = followups_for_session(db, session_id)
    feedbacks = feedback_for_session(db, session_id)
    # 对话式面试的深挖题（order 0）不作为逐题卡片展示
    visible_questions = (
        [q for q in questions if q.order != 0] if session.mode == "dialog" else questions
    )
    current = next(
        (
            question
            for question in visible_questions
            if question.id not in answered_question_ids
            or (question.id in followups and followups[question.id].status == "pending")
        ),
        None,
    )
    completed = len({answer.question_id for answer in answers if answer.question_id in {q.id for q in visible_questions}})
    if (
        session.mode != "dialog"
        and completed == len(questions)
        and session.status != "completed"
    ):
        session.status = "completed"
        session.current_question_index = len(questions)
        db.commit()
    timeline = session_timeline(db, session) if session.mode == "dialog" else []
    return {
        "session_id": session.id,
        "status": session.status,
        "interview_type": interview_type_from_mode(session.mode),
        "mode": session.mode,
        "stage": session.stage,
        # 当前题同样要带追问/反馈状态：前端面试页从 current_question 渲染追问卡
        "current_question": (
            {
                **_question_response(current),
                "answered": current.id in answered_question_ids,
                "followup": _followup_view(followups.get(current.id)),
                "feedback": _feedback_view(feedbacks.get(current.id)),
            }
            if current
            else None
        ),
        "questions": [
            {
                **_question_response(question),
                "answered": question.id in answered_question_ids,
                "followup": _followup_view(followups.get(question.id)),
                "feedback": _feedback_view(feedbacks.get(question.id)),
            }
            for question in visible_questions
        ],
        "progress": {"completed": completed, "total": len(visible_questions)},
        "timeline": timeline,
    }


def _followup_view(followup) -> dict | None:
    if followup is None or followup.status == "waived":
        return None
    return {
        "id": followup.id,
        "question_text": followup.question_text,
        "decision_reason": followup.decision_reason,
        "status": followup.status,
        "answer_text": followup.answer_text,
    }


def _feedback_view(feedback) -> dict | None:
    if feedback is None:
        return None
    return {
        "content": feedback.content,
        "focus_hints": json.loads(feedback.focus_hints_json),
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
        run = _latest_assessment_run(db, existing.id)
        return _answer_result_response(existing, run, db)

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
    if session.mode == "dialog":
        # 对话式面试：以实际已答题目数判断（深挖题不经 submit_answer 创建）
        answered_count = len(
            {
                row
                for row in db.scalars(
                    select(AnswerAttempt.question_id).where(
                        AnswerAttempt.session_id == session_id
                    )
                )
            }
        )
        if answered_count >= session.total_questions:
            if session.stage == "knowledge":
                from .dialog_flow import enter_wrap_up

                enter_wrap_up(db, session)
    elif session.current_question_index >= session.total_questions:
        session.status = "completed"
    db.commit()
    return _answer_result_response(answer, None, db)
