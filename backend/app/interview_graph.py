"""LangGraph skeleton for a contextual, resumable interview."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Callable, Literal, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.interview_graph_types import (
    EvidenceVerification,
    InterviewGraphState,
    InterviewPlan,
    InterviewerTurn,
    MAX_FOLLOWUPS_PER_NODE,
)


Route = Literal["ask", "advance", "wrap_up"]


class InterviewGraphAgents(Protocol):
    """Role methods consumed by the graph; concrete providers arrive later."""

    def plan(self, state: InterviewGraphState) -> InterviewPlan: ...

    def ask(self, state: InterviewGraphState) -> InterviewerTurn: ...

    def verify(self, state: InterviewGraphState) -> EvidenceVerification: ...

    def evaluate(self, state: InterviewGraphState) -> Mapping[str, object]: ...

    def report(self, state: InterviewGraphState) -> Mapping[str, object]: ...


def _dump(value: object) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"expected a mapping-like agent output, got {type(value)!r}")


def _current_node(state: InterviewGraphState) -> dict:
    plan = state.get("plan", [])
    index = state.get("current_node_index", 0)
    if 0 <= index < len(plan):
        return dict(plan[index])
    return {"node_id": "unknown", "kind": "architecture", "opening_question": "请继续介绍。"}


def _current_kind(state: InterviewGraphState) -> str:
    return str(_current_node(state).get("kind", "architecture"))


def _current_followup_key(state: InterviewGraphState) -> str:
    return str(_current_node(state).get("node_id", "unknown"))


def route_after_verification(state: InterviewGraphState) -> Route:
    """Choose the next graph edge without consulting an LLM."""

    route = state.get("route", "insufficient")
    if route == "completed":
        return "wrap_up"

    if route in {"conflict", "insufficient"}:
        node = _current_node(state)
        node_id = _current_followup_key(state)
        legacy_kind = str(node.get("kind", "architecture"))
        followups = state.get("followups_used", {})
        used = followups.get(node_id, followups.get(legacy_kind, 0))
        return "ask" if used < MAX_FOLLOWUPS_PER_NODE else "advance"

    if route == "covered":
        plan = state.get("plan", [])
        if plan and state.get("current_node_index", 0) >= len(plan) - 1:
            return "wrap_up"
        return "advance"

    return "advance"


def _route_after_advance(state: InterviewGraphState) -> Literal["ask", "wrap_up"]:
    plan = state.get("plan", [])
    if state.get("current_node_index", 0) >= len(plan):
        return "wrap_up"
    return "ask"


def build_interview_graph(
    agents: InterviewGraphAgents,
    checkpointer: BaseCheckpointSaver,
    event_sink: Callable[[Mapping[str, object]], None] | None = None,
):
    """Compile the interview graph with an injected checkpointer."""

    def load_context(state: InterviewGraphState) -> dict:
        return {"status": "planning"}

    def question_id(state: InterviewGraphState) -> str:
        node = _current_node(state)
        node_id = str(node.get("node_id", "unknown"))
        followups = state.get("followups_used", {})
        used = followups.get(node_id, followups.get(str(node.get("kind", "")), 0))
        return f"graph-{state.get('session_id', 'session')}-{node_id}-{int(used or 0)}"

    def emit(state: InterviewGraphState, event_kind: str, graph_step_id: str, payload: dict) -> None:
        if event_sink is not None:
            event_sink(
                {
                    "session_id": str(state.get("session_id", "")),
                    "graph_step_id": graph_step_id,
                    "event_kind": event_kind,
                    "payload": payload,
                }
            )

    def planner(state: InterviewGraphState) -> dict:
        plan = state.get("plan", [])
        plan_method = getattr(agents, "plan", None)
        if callable(plan_method):
            result = plan_method(state)
            plan = _dump(result).get("nodes", [])
        return {"plan": plan, "current_node_index": 0, "status": "planning"}

    def interviewer(state: InterviewGraphState) -> dict:
        node = _current_node(state)
        ask_method = getattr(agents, "ask", None)
        if callable(ask_method):
            turn = _dump(ask_method(state))
            text = str(turn.get("question", node.get("opening_question", "请继续介绍。")))
            question_kind = str(turn.get("kind", "followup" if state.get("last_answer") else "opening"))
        else:
            text = str(node.get("opening_question", "请继续介绍。"))
            question_kind = "followup" if state.get("last_answer") else "opening"

        question = {"node_id": str(node.get("node_id", "unknown")), "text": text, "kind": question_kind}
        current_question_id = question_id(state)
        emit(
            state,
            "question_ready",
            f"question:{current_question_id}",
            {
                "question_id": current_question_id,
                "node_id": question["node_id"],
                "kind": question_kind,
                "text": text,
                "order": state.get("current_node_index", 0),
            },
        )
        message = {"role": "interviewer", "node_id": question["node_id"], "content": text}
        return {"current_question": question, "messages": [message], "status": "awaiting_answer"}

    def wait_for_candidate(state: InterviewGraphState) -> dict:
        question = state.get("current_question") or {}
        answer = interrupt({"question": question, "type": "candidate_answer"})
        content = answer.get("content") if isinstance(answer, Mapping) else answer
        content = str(content or "").strip()
        if not content:
            raise ValueError("candidate answer cannot be empty")
        node_id = str(question.get("node_id", "unknown"))
        current_question_id = question_id(state)
        submission_id = (
            str(answer.get("client_submission_id"))
            if isinstance(answer, Mapping) and answer.get("client_submission_id")
            else f"graph-{current_question_id}"
        )
        emit(
            state,
            "candidate_answer",
            f"answer:{current_question_id}",
            {
                "question_id": current_question_id,
                "client_submission_id": submission_id,
                "answer_text": content,
                "status": "submitted",
            },
        )
        return {
            "last_answer": {"node_id": node_id, "content": content},
            "messages": [{"role": "candidate", "node_id": node_id, "content": content}],
            "status": "verifying",
        }

    def evidence_verifier(state: InterviewGraphState) -> dict:
        verify_method = getattr(agents, "verify", None)
        if callable(verify_method):
            verification = EvidenceVerification.model_validate(_dump(verify_method(state)))
        else:
            verification = EvidenceVerification(
                claims=[],
                covered_targets=[],
                missing_targets=[],
                conflicts=[],
                confidence=0,
                route="covered",
            )

        node = _current_node(state)
        node_id = str(node.get("node_id", "unknown"))
        kind = _current_kind(state)
        coverage = {key: list(value) for key, value in state.get("coverage", {}).items()}
        covered = list(coverage.get(node_id, []))
        for target in verification.covered_targets:
            if target not in covered:
                covered.append(target)
        coverage[node_id] = covered

        conflicts = list(state.get("conflicts", []))
        conflicts.extend({"target": kind, "detail": conflict} for conflict in verification.conflicts)
        followups_used = dict(state.get("followups_used", {}))
        if verification.route in {"conflict", "insufficient"}:
            followup_key = _current_followup_key(state)
            used = followups_used.get(followup_key, followups_used.get(kind, 0))
            followups_used[followup_key] = min(MAX_FOLLOWUPS_PER_NODE, used + 1)
            if followup_key != kind:
                followups_used.pop(kind, None)

        return {
            "route": verification.route,
            "coverage": coverage,
            "conflicts": conflicts,
            "followups_used": followups_used,
            "status": "verifying",
        }

    def advance_plan(state: InterviewGraphState) -> dict:
        return {
            "current_node_index": state.get("current_node_index", 0) + 1,
            "current_question": None,
            "last_answer": None,
            "route": "covered",
            "status": "planning",
        }

    def wrap_up(state: InterviewGraphState) -> dict:
        return {"route": "completed", "status": "completed", "current_question": None}

    def finalize_transcript(state: InterviewGraphState) -> dict:
        return {"status": "completed"}

    def evaluator(state: InterviewGraphState) -> dict:
        evaluate_method = getattr(agents, "evaluate", None)
        if callable(evaluate_method):
            evaluate_method(state)
        return {}

    def report(state: InterviewGraphState) -> dict:
        report_method = getattr(agents, "report", None)
        if callable(report_method):
            report_method(state)
        return {"status": "completed"}

    graph = StateGraph(InterviewGraphState)
    for name, node in (
        ("load_context", load_context),
        ("planner", planner),
        ("interviewer", interviewer),
        ("wait_for_candidate", wait_for_candidate),
        ("evidence_verifier", evidence_verifier),
        ("advance_plan", advance_plan),
        ("wrap_up", wrap_up),
        ("finalize_transcript", finalize_transcript),
        ("evaluator", evaluator),
        ("report", report),
    ):
        graph.add_node(name, node)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "planner")
    graph.add_edge("planner", "interviewer")
    graph.add_edge("interviewer", "wait_for_candidate")
    graph.add_edge("wait_for_candidate", "evidence_verifier")
    graph.add_conditional_edges(
        "evidence_verifier",
        route_after_verification,
        {"ask": "interviewer", "advance": "advance_plan", "wrap_up": "wrap_up"},
    )
    graph.add_conditional_edges(
        "advance_plan",
        _route_after_advance,
        {"ask": "interviewer", "wrap_up": "wrap_up"},
    )
    graph.add_edge("wrap_up", "finalize_transcript")
    graph.add_edge("finalize_transcript", "evaluator")
    graph.add_edge("evaluator", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)
