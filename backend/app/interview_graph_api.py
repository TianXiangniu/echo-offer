"""HTTP lifecycle for the resumable contextual interview graph."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Callable, Iterator, Mapping
from datetime import timedelta
from threading import Lock
from uuid import uuid4

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .interview_flow import get_session_view
from .interview_graph_runtime import graph_config
from .models import (
    AnswerAttempt,
    InterviewGraphEventReceipt,
    InterviewGraphSubmissionReceipt,
    InterviewSession,
    ResumeProjectAnalysis,
    ResumeProject,
    ensure_utc,
    utc_now,
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

_submission_locks: dict[str, Lock] = {}
_submission_locks_guard = Lock()
_SUBMISSION_TTL = timedelta(hours=2)


def _submission_lock(session_id: str) -> Lock:
    # ponytail: local lock reduces duplicate work; the durable receipt below covers other workers.
    with _submission_locks_guard:
        return _submission_locks.setdefault(session_id, Lock())


def _submission_hash(answer_text: str) -> str:
    return hashlib.sha256(answer_text.encode("utf-8")).hexdigest()


def _existing_submission_result(
    db: Session,
    existing: InterviewGraphSubmissionReceipt,
    answer_hash: str,
) -> bool:
    if existing.answer_text_hash != answer_hash:
        raise ConflictError("client_submission_id was already used with different content")
    if existing.status == "completed":
        return False
    if (
        existing.status == "processing"
        and ensure_utc(existing.created_at) <= utc_now() - _SUBMISSION_TTL
    ):
        existing.status = "failed"
        db.commit()
        raise ConflictError("client_submission_id expired after a failed processing attempt; use a new id")
    raise ConflictError("client_submission_id is already processing or has failed")


def _reserve_submission(db: Session, session_id: str, payload: GraphAnswerSubmission) -> bool:
    """Reserve a submission before graph/model work; return False for a completed duplicate."""

    answer_hash = _submission_hash(payload.answer_text)
    existing = db.scalar(
        select(InterviewGraphSubmissionReceipt).where(
            InterviewGraphSubmissionReceipt.session_id == session_id,
            InterviewGraphSubmissionReceipt.client_submission_id == payload.client_submission_id,
        )
    )
    if existing is not None:
        return _existing_submission_result(db, existing, answer_hash)

    db.add(
        InterviewGraphSubmissionReceipt(
            id=str(uuid4()),
            session_id=session_id,
            client_submission_id=payload.client_submission_id,
            answer_text_hash=answer_hash,
            status="processing",
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(InterviewGraphSubmissionReceipt).where(
                InterviewGraphSubmissionReceipt.session_id == session_id,
                InterviewGraphSubmissionReceipt.client_submission_id == payload.client_submission_id,
            )
        )
        if existing is None:
            raise
        return _existing_submission_result(db, existing, answer_hash)
    return True


def _set_submission_status(db: Session, session_id: str, client_submission_id: str, status: str) -> None:
    db.rollback()
    receipt = db.scalar(
        select(InterviewGraphSubmissionReceipt).where(
            InterviewGraphSubmissionReceipt.session_id == session_id,
            InterviewGraphSubmissionReceipt.client_submission_id == client_submission_id,
        )
    )
    if receipt is not None:
        receipt.status = status
        db.commit()


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


def _public_state(db: Session, session_id: str, graph, *, repair: bool = True) -> dict:
    state = graph.get_state(graph_config(session_id)).values
    if repair:
        _repair_projection(db, session_id, state)
    return get_session_view(db, session_id, state)


def _attach_completion_result(
    state: dict,
    on_completed: Callable[[], Mapping] | None,
) -> dict:
    if on_completed is not None and state.get("status") == "completed":
        try:
            state["assessment"] = dict(on_completed())
        except ConflictError as error:
            state["assessment"] = {
                "status": "pending",
                "batch_id": None,
                "job_id": None,
                "job_status": None,
                "job_error_code": "assessment_incomplete",
                "job_error_message": str(error),
                "evaluated_count": 0,
                "total_count": 0,
                "assessments": [],
            }
    return state


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


def start_graph(
    db: Session,
    session_id: str,
    *,
    graph_builder,
    agents,
    checkpointer,
    on_completed: Callable[[], Mapping] | None = None,
) -> dict:
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
    return _attach_completion_result(
        _public_state(db, session.id, graph),
        on_completed,
    )


def _resume_graph_locked(
    db: Session,
    session_id: str,
    payload: GraphAnswerSubmission,
    *,
    graph_builder,
    agents,
    checkpointer,
    on_completed: Callable[[], Mapping] | None = None,
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
        return _attach_completion_result(
            _public_state(db, session.id, graph),
            on_completed,
        )

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
        return _attach_completion_result(
            _public_state(db, session.id, graph, repair=False),
            on_completed,
        )
    if not _reserve_submission(db, session.id, payload):
        return _attach_completion_result(
            _public_state(db, session.id, graph),
            on_completed,
        )
    try:
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
    except Exception:
        _set_submission_status(db, session.id, payload.client_submission_id, "failed")
        raise
    _set_submission_status(db, session.id, payload.client_submission_id, "completed")
    return _attach_completion_result(
        _public_state(db, session.id, graph),
        on_completed,
    )


def resume_graph(
    db: Session,
    session_id: str,
    payload: GraphAnswerSubmission,
    *,
    graph_builder,
    agents,
    checkpointer,
    on_completed: Callable[[], Mapping] | None = None,
) -> dict:
    with _submission_lock(session_id):
        return _resume_graph_locked(
            db,
            session_id,
            payload,
            graph_builder=graph_builder,
            agents=agents,
            checkpointer=checkpointer,
            on_completed=on_completed,
        )


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
