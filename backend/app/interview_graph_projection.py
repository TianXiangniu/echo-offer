"""Project safe LangGraph events into the existing interview tables."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .interview_graph_types import MAX_FOLLOWUPS_PER_NODE
from .models import (
    AnswerAttempt,
    InterviewGraphEventReceipt,
    InterviewQuestion,
    InterviewSession,
    ProjectDialog,
    utc_now,
)
from .workflow_common import ConflictError, NotFoundError, _hash_payload


_EVENT_KINDS = {"question_ready", "candidate_answer", "state_updated", "completed"}


def _event_value(event: object, key: str, default=None):
    if isinstance(event, Mapping):
        return event.get(key, default)
    return getattr(event, key, default)


def _payload(event: object) -> dict:
    value = _event_value(event, "payload", {})
    if not isinstance(value, Mapping):
        raise ValueError("graph event payload must be an object")
    return dict(value)


def _text(payload: Mapping, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _question_payload(payload: Mapping) -> dict:
    nested = payload.get("question") or payload.get("current_question")
    return {**(dict(nested) if isinstance(nested, Mapping) else {}), **dict(payload)}


def _next_turn_no(db: Session, session_id: str) -> int:
    maximum = db.scalar(
        select(func.max(ProjectDialog.turn_no)).where(ProjectDialog.session_id == session_id)
    )
    return (maximum or 0) + 1


def _apply_state(session: InterviewSession, payload: Mapping) -> None:
    if isinstance(payload.get("status"), str):
        session.status = payload["status"][:30]
    if isinstance(payload.get("stage"), str):
        session.stage = payload["stage"][:20]
    index = payload.get("current_question_index")
    if isinstance(index, int) and index >= 0:
        session.current_question_index = index


def _project_question(db: Session, session: InterviewSession, payload: Mapping) -> None:
    data = _question_payload(payload)
    prompt = _text(data, "text", "prompt", "question")
    if not prompt:
        raise ValueError("question_ready event requires question text")
    question_id = str(data.get("question_id") or uuid4())
    question = db.get(InterviewQuestion, question_id)
    if question is not None and question.session_id != session.id:
        raise ConflictError("graph question id belongs to another session")
    if question is None:
        order = data.get("order")
        if not isinstance(order, int) or order < 0:
            order = session.current_question_index
        question = InterviewQuestion(
            id=question_id,
            session_id=session.id,
            order=order,
            category=str(data.get("category") or data.get("kind") or "graph")[:30],
            is_anchor=bool(data.get("is_anchor", False)),
            prompt=prompt,
            knowledge_point_id=str(data.get("knowledge_point_id") or f"graph.{data.get('node_id', 'unknown')}")[:120],
            template_id=str(data["template_id"])[:160] if data.get("template_id") else None,
            rubric_version=str(data.get("rubric_version") or "graph-v1")[:60],
            signals_json=json.dumps(data.get("signals", []), ensure_ascii=False),
            rubric_json=data.get("rubric_json", "{}")
            if isinstance(data.get("rubric_json", "{}"), str)
            else json.dumps(data.get("rubric_json", {}), ensure_ascii=False),
        )
        db.add(question)
        db.flush()
    db.add(
        ProjectDialog(
            id=str(uuid4()),
            session_id=session.id,
            turn_no=_next_turn_no(db, session.id),
            role="interviewer",
            content=prompt,
            kind="graph_question",
        )
    )
    session.current_question_index = max(session.current_question_index, question.order)
    session.stage = "graph"
    session.status = "in_progress"


def _project_answer(db: Session, session: InterviewSession, payload: Mapping) -> None:
    answer_text = _text(payload, "answer_text", "content", "answer")
    if not answer_text:
        raise ValueError("candidate_answer event requires answer_text")
    question_id = payload.get("question_id")
    question = db.get(InterviewQuestion, str(question_id)) if question_id else db.scalar(
        select(InterviewQuestion)
        .where(InterviewQuestion.session_id == session.id)
        .order_by(InterviewQuestion.order.desc())
    )
    if question is None or question.session_id != session.id:
        raise NotFoundError("graph question not found")
    client_submission_id = str(
        payload.get("client_submission_id") or f"graph-{session.id}-{question.id}"
    )[:120]
    answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(AnswerAttempt).where(
            AnswerAttempt.session_id == session.id,
            AnswerAttempt.client_submission_id == client_submission_id,
        )
    )
    if existing is not None:
        if existing.question_id != question.id or existing.answer_text_hash != answer_hash:
            raise ConflictError("graph answer submission conflict")
    else:
        payload_hash = _hash_payload(
            {
                "question_id": question.id,
                "client_submission_id": client_submission_id,
                "answer_text": answer_text,
                "status": str(payload.get("status") or "submitted"),
            }
        )
        db.add(
            AnswerAttempt(
                id=str(uuid4()),
                session_id=session.id,
                question_id=question.id,
                client_submission_id=client_submission_id,
                primary_attempt_kind="primary",
                status=str(payload.get("status") or "submitted")[:30],
                answer_text=answer_text,
                answer_text_hash=answer_hash,
                payload_hash=payload_hash,
            )
        )
        db.add(
            ProjectDialog(
                id=str(uuid4()),
                session_id=session.id,
                turn_no=_next_turn_no(db, session.id),
                role="candidate",
                content=answer_text,
                kind="graph_answer",
            )
        )
    session.current_question_index = max(session.current_question_index, question.order + 1)
    session.stage = "graph"


def project_graph_event(db: Session, event: object) -> bool:
    """Apply one graph event once; replay returns False, conflicting replay raises 409."""

    session_id = str(_event_value(event, "session_id", ""))
    graph_step_id = str(_event_value(event, "graph_step_id", ""))
    event_kind = str(_event_value(event, "event_kind", ""))
    if not session_id or not graph_step_id or event_kind not in _EVENT_KINDS:
        raise ValueError("invalid graph event envelope")
    payload = _payload(event)
    payload_hash = _hash_payload(payload)
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    existing = db.scalar(
        select(InterviewGraphEventReceipt).where(
            InterviewGraphEventReceipt.session_id == session_id,
            InterviewGraphEventReceipt.graph_step_id == graph_step_id,
            InterviewGraphEventReceipt.event_kind == event_kind,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise ConflictError("graph event payload conflict")
        return False

    receipt = InterviewGraphEventReceipt(
        id=str(uuid4()),
        session_id=session_id,
        graph_step_id=graph_step_id,
        event_kind=event_kind,
        payload_hash=payload_hash,
        created_at=utc_now(),
    )
    try:
        with db.begin_nested():
            db.add(receipt)
            db.flush()
            if event_kind == "question_ready":
                _project_question(db, session, payload)
            elif event_kind == "candidate_answer":
                _project_answer(db, session, payload)
            else:
                _apply_state(session, payload)
        db.commit()
    except IntegrityError:
        existing = db.scalar(
            select(InterviewGraphEventReceipt).where(
                InterviewGraphEventReceipt.session_id == session_id,
                InterviewGraphEventReceipt.graph_step_id == graph_step_id,
                InterviewGraphEventReceipt.event_kind == event_kind,
            )
        )
        if existing is not None and existing.payload_hash == payload_hash:
            return False
        raise ConflictError("graph event payload conflict")
    except Exception:
        db.rollback()
        raise
    return True


def graph_timeline(db: Session, session: InterviewSession, graph_state: Mapping | None = None) -> list[dict]:
    items = [
        {
            "role": row.role,
            "kind": row.kind,
            "content": row.content,
        }
        for row in db.scalars(
            select(ProjectDialog)
            .where(ProjectDialog.session_id == session.id)
            .order_by(ProjectDialog.turn_no, ProjectDialog.role)
        )
    ]
    if items or not isinstance(graph_state, Mapping):
        return items
    return [
        {
            "role": item.get("role", "interviewer"),
            "kind": "graph",
            "content": item.get("content", ""),
        }
        for item in graph_state.get("messages", [])
        if isinstance(item, Mapping) and item.get("content")
    ]


def graph_session_view(
    db: Session,
    session: InterviewSession,
    graph_state: Mapping | None = None,
) -> dict:
    """Expose graph progress in the legacy session-view shape without raw state."""

    state = graph_state if isinstance(graph_state, Mapping) else {}
    persisted_questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session.id)
            .order_by(InterviewQuestion.order)
        )
    )
    answered_ids = {
        answer.question_id
        for answer in db.scalars(
            select(AnswerAttempt).where(AnswerAttempt.session_id == session.id)
        )
    }
    plan = [node for node in state.get("plan", []) if isinstance(node, Mapping)]
    if not plan:
        plan = [
            {
                "node_id": question.knowledge_point_id.removeprefix("graph."),
                "kind": question.category,
                "goal": question.prompt,
                "opening_question": question.prompt,
            }
            for question in persisted_questions
        ]
    index = state.get("current_node_index", session.current_question_index)
    index = index if isinstance(index, int) and index >= 0 else 0
    if not state and persisted_questions:
        index = next(
            (
                question.order
                for question in persisted_questions
                if question.id not in answered_ids
            ),
            len(plan),
        )
    route = str(state.get("route", ""))
    followups = state.get("followups_used", {})
    followups = followups if isinstance(followups, Mapping) else {}
    nodes = []
    for position, node in enumerate(plan):
        node_id = str(node.get("node_id", position))
        if position < index or (str(state.get("status")) == "completed" and position == index):
            node_status = "covered"
        elif position > index:
            node_status = "not_started"
        elif route in {"conflict", "insufficient"} and int(followups.get(node_id, 0) or 0) >= MAX_FOLLOWUPS_PER_NODE:
            node_status = "needs_confirmation"
        else:
            node_status = "active"
        nodes.append(
            {
                "id": node_id,
                "kind": str(node.get("kind", "graph")),
                "label": str(node.get("goal") or node.get("kind") or node_id),
                "status": node_status,
            }
        )
    current = state.get("current_question")
    if isinstance(current, Mapping):
        current_question = {
            "id": str(current.get("node_id", "current")),
            "order": index,
            "category": str(current.get("kind", "graph")),
            "is_anchor": False,
            "prompt": str(current.get("text", "")),
            "knowledge_point_id": f"graph.{current.get('node_id', 'current')}",
            "template_id": None,
            "rubric_version": "graph-v1",
        }
    else:
        persisted_current = next(
            (question for question in persisted_questions if question.id not in answered_ids),
            None,
        )
        current_question = (
            {
                "id": persisted_current.id,
                "order": persisted_current.order,
                "category": persisted_current.category,
                "is_anchor": persisted_current.is_anchor,
                "prompt": persisted_current.prompt,
                "knowledge_point_id": persisted_current.knowledge_point_id,
                "template_id": persisted_current.template_id,
                "rubric_version": persisted_current.rubric_version,
            }
            if persisted_current is not None
            else None
        )
    status = str(state.get("status") or session.status)
    return {
        "session_id": session.id,
        "status": status,
        "mode": "graph",
        "stage": "graph",
        "current_question": current_question,
        "questions": [
            {
                "id": node["id"],
                "order": position,
                "category": node["kind"],
                "is_anchor": position == 0,
                "prompt": str(plan[position].get("opening_question", "")),
                "knowledge_point_id": f"graph.{node['id']}",
                "template_id": None,
                "rubric_version": "graph-v1",
                "answered": node["status"] == "covered"
                or (
                    position < len(persisted_questions)
                    and persisted_questions[position].id in answered_ids
                ),
            }
            for position, node in enumerate(nodes)
        ],
        "nodes": nodes,
        "progress": {"completed": min(index, len(plan)), "total": len(plan)},
        "timeline": graph_timeline(db, session, state),
    }
