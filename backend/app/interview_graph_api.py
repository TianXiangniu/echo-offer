"""HTTP lifecycle for the resumable contextual interview graph."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from .interview_flow import get_session_view
from .interview_graph_runtime import graph_config
from .models import (
    AnswerAttempt,
    InterviewGraphEventReceipt,
    InterviewSession,
    ResumeProjectAnalysis,
    ResumeProject,
)
from .schemas import GraphAnswerSubmission
from .interview_graph_projection import project_graph_event
from .workflow_common import ConflictError, NotFoundError, _get_active_session


_PROJECT_CONTEXT_FIELDS = (
    ("background_goal", "background_goal"),
    ("tech_stack", "tech_stack"),
    ("responsibilities", "responsibilities"),
    ("core_solution", "core_solution"),
    ("engineering_challenges", "engineering_challenges"),
    ("failure_improvements", "failure_improvements"),
    ("quantified_results", "quantified_results"),
)


def _compact_context_text(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_graph_context(
    project: ResumeProject,
    analysis: ResumeProjectAnalysis | None = None,
) -> dict:
    """Build the smallest safe project context for the LangGraph state."""

    project_context = {
        "project_id": project.id,
        "name": _compact_context_text(project.project_name, 200),
        "summary": _compact_context_text(project.background_goal, 1000),
    }
    project_values = {
        attribute: _compact_context_text(getattr(project, attribute, ""), 1000)
        for _, attribute in _PROJECT_CONTEXT_FIELDS
    }
    facts: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    if analysis is not None and analysis.status == "confirmed":
        try:
            snapshot = json.loads(analysis.analysis_json or "{}")
        except (TypeError, json.JSONDecodeError):
            snapshot = {}
        raw_facts = snapshot.get("facts", []) if isinstance(snapshot, Mapping) else []
        if isinstance(raw_facts, Mapping):
            raw_facts = [raw_facts]
        if isinstance(raw_facts, list):
            for index, raw_fact in enumerate(raw_facts, start=1):
                if not isinstance(raw_fact, Mapping):
                    continue
                if raw_fact.get("status") not in {"extracted", "confirmed"}:
                    continue
                value = _compact_context_text(raw_fact.get("value"))
                if not value:
                    continue
                fact_id = _compact_context_text(raw_fact.get("fact_id") or f"analysis:{index}", 128)
                if not fact_id or fact_id in seen_ids:
                    continue
                seen_ids.add(fact_id)
                facts.append(
                    {
                        "fact_id": fact_id,
                        "field": _compact_context_text(raw_fact.get("field") or "project_fact", 160),
                        "value": value,
                    }
                )

    if not facts:
        for public_name, attribute in _PROJECT_CONTEXT_FIELDS:
            value = project_values.get(attribute, "")
            if value:
                facts.append(
                    {
                        "fact_id": f"project:{attribute}",
                        "field": attribute,
                        "value": value,
                    }
                )
    return {"project": project_context, "verified_facts": facts}


def _graph_session(db: Session, session_id: str) -> tuple[InterviewSession, ResumeProject]:
    session = _get_active_session(db, session_id)
    if session.mode != "graph":
        raise ConflictError("session is not a graph interview")
    project = db.get(ResumeProject, session.resume_project_id)
    if project is None:
        raise NotFoundError("project not found")
    return session, project


def _initial_state(
    session: InterviewSession,
    project: ResumeProject,
    analysis: ResumeProjectAnalysis | None = None,
) -> dict:
    context = build_graph_context(project, analysis)
    return {
        "session_id": session.id,
        **context,
        "plan": [],
        "current_node_index": 0,
        "current_question": None,
        "messages": [],
        "graph_events": [],
        "last_answer": None,
        "coverage": {},
        "conflicts": [],
        "followups_used": {},
        "route": "covered",
        "status": "planning",
        "error": None,
    }


def _repair_projection(db: Session, session_id: str, state: Mapping) -> None:
    events = state.get("graph_events", [])
    if not isinstance(events, list) or not events:
        return
    db.rollback()
    try:
        for event in events:
            if isinstance(event, Mapping):
                project_graph_event(db, event, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _public_state(db: Session, session_id: str, graph) -> dict:
    state = graph.get_state(graph_config(session_id)).values
    _repair_projection(db, session_id, state)
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
    analysis = db.get(ResumeProjectAnalysis, project.analysis_id) if project.analysis_id else None
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
            lambda: graph.invoke(
                _initial_state(session, project, analysis),
                graph_config(session.id),
            ),
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
    checkpoint = graph.get_state(graph_config(session.id)).values
    if checkpoint.get("status") == "completed":
        return _public_state(db, session.id, graph)
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
