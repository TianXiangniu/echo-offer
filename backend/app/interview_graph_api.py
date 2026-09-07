"""HTTP lifecycle for the resumable contextual interview graph."""

from __future__ import annotations

import json
from collections.abc import Iterator

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from .interview_flow import get_session_view
from .interview_graph_runtime import graph_config
from .models import (
    AnswerAttempt,
    InterviewGraphEventReceipt,
    InterviewSession,
    ResumeProject,
)
from .schemas import GraphAnswerSubmission
from .interview_graph_projection import project_graph_event
from .workflow_common import ConflictError, NotFoundError, _get_active_session


def _graph_session(db: Session, session_id: str) -> tuple[InterviewSession, ResumeProject]:
    session = _get_active_session(db, session_id)
    if session.mode != "graph":
        raise ConflictError("session is not a graph interview")
    project = db.get(ResumeProject, session.resume_project_id)
    if project is None:
        raise NotFoundError("project not found")
    return session, project


def _initial_state(session: InterviewSession, project: ResumeProject) -> dict:
    return {
        "session_id": session.id,
        "project": {
            "project_id": project.id,
            "name": project.project_name,
            "summary": project.background_goal,
        },
        "verified_facts": [],
        "plan": [],
        "current_node_index": 0,
        "current_question": None,
        "messages": [],
        "last_answer": None,
        "coverage": {},
        "conflicts": [],
        "followups_used": {},
        "route": "covered",
        "status": "planning",
        "error": None,
    }


def _public_state(db: Session, session_id: str, graph) -> dict:
    state = graph.get_state(graph_config(session_id)).values
    return get_session_view(db, session_id, state)


def _build_graph(*, graph_builder, agents, checkpointer, db: Session, events: list):
    return graph_builder(
        agents,
        checkpointer,
        db,
        event_sink=events.append,
    )


def _invoke_and_project(db: Session, invoke, events: list[dict]) -> None:
    db.rollback()
    try:
        invoke()
        for event in events:
            project_graph_event(db, event, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise


def start_graph(db: Session, session_id: str, *, graph_builder, agents, checkpointer) -> dict:
    session, project = _graph_session(db, session_id)
    events: list[dict] = []
    graph = _build_graph(
        graph_builder=graph_builder,
        agents=agents,
        checkpointer=checkpointer,
        db=db,
        events=events,
    )
    existing = graph.get_state(graph_config(session.id)).values
    if not existing:
        _invoke_and_project(
            db,
            lambda: graph.invoke(_initial_state(session, project), graph_config(session.id)),
            events,
        )
    return _public_state(db, session.id, graph)


def resume_graph(
    db: Session,
    session_id: str,
    payload: GraphAnswerSubmission,
    *,
    graph_builder,
    agents,
    checkpointer,
) -> dict:
    session, _ = _graph_session(db, session_id)
    existing = db.scalar(
        select(AnswerAttempt).where(
            AnswerAttempt.session_id == session.id,
            AnswerAttempt.client_submission_id == payload.client_submission_id,
        )
    )
    if existing is not None:
        if existing.answer_text != payload.answer_text:
            raise ConflictError("client_submission_id was already used with different content")
        graph = _build_graph(
            graph_builder=graph_builder,
            agents=agents,
            checkpointer=checkpointer,
            db=db,
            events=[],
        )
        return _public_state(db, session.id, graph)

    events: list[dict] = []
    graph = _build_graph(
        graph_builder=graph_builder,
        agents=agents,
        checkpointer=checkpointer,
        db=db,
        events=events,
    )
    _invoke_and_project(
        db,
        lambda: graph.invoke(
            Command(
                resume={
                    "content": payload.answer_text,
                    "client_submission_id": payload.client_submission_id,
                }
            ),
            graph_config(session.id),
        ),
        events,
    )
    return _public_state(db, session.id, graph)


def graph_state(db: Session, session_id: str, *, graph_builder, agents, checkpointer) -> dict:
    _graph_session(db, session_id)
    graph = _build_graph(
        graph_builder=graph_builder,
        agents=agents,
        checkpointer=checkpointer,
        db=db,
        events=[],
    )
    return _public_state(db, session_id, graph)


def graph_events(db: Session, session_id: str) -> Iterator[str]:
    session, _ = _graph_session(db, session_id)
    rows = db.scalars(
        select(InterviewGraphEventReceipt)
        .where(InterviewGraphEventReceipt.session_id == session.id)
        .order_by(InterviewGraphEventReceipt.created_at, InterviewGraphEventReceipt.id)
    )
    for row in rows:
        event_kind = row.event_kind if row.event_kind in {
            "question_ready", "candidate_answer", "state_updated", "completed"
        } else "state_updated"
        data = {"graph_step_id": row.graph_step_id, "event_kind": event_kind}
        yield f"event: {event_kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
