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
    InterviewPlanNode,
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


_FALLBACK_NODE_SPECS = (
    (
        "opening",
        "确认项目背景、业务目标和个人职责边界",
        "请先介绍你在「{project}」中的业务目标、个人职责和团队边界。",
        ("业务目标", "个人职责", "团队边界"),
    ),
    (
        "project",
        "确认项目输入输出和关键使用场景",
        "请说明「{project}」的核心输入、输出和最重要的使用场景。",
        ("输入输出", "使用场景"),
    ),
    (
        "architecture",
        "验证核心组件、数据流和状态流",
        "请说明「{project}」的核心架构和数据流，哪些组件由你负责？",
        ("组件职责", "数据流", "边界"),
    ),
    (
        "challenge",
        "验证故障定位、可靠性和恢复方式",
        "请讲一个「{project}」中遇到的故障或工程难点，以及你如何定位和恢复。",
        ("故障案例", "定位过程", "恢复方式"),
    ),
    (
        "tradeoff",
        "验证方案取舍、约束和替代方案",
        "在「{project}」中你做过哪些方案取舍？为什么没有选择其他方案？",
        ("备选方案", "约束", "取舍原因"),
    ),
    (
        "evidence",
        "验证效果、稳定性和成本的量化方法",
        "你如何验证「{project}」的效果、稳定性或成本变化？请说明指标和基线。",
        ("指标", "基线", "验证方法"),
    ),
)


def _is_model_failure(error: Exception) -> bool:
    """Recognize provider/parser failures without hiding graph programming bugs."""

    return isinstance(error, (ValueError, TypeError)) or bool(getattr(error, "code", None))


def fallback_interview_plan(state: Mapping) -> InterviewPlan:
    """Return a fact-neutral six-node plan when planning is unavailable."""

    project = "这个项目"
    project_state = state.get("project")
    if isinstance(project_state, Mapping):
        project = str(project_state.get("name") or project).strip()[:120] or project
    return InterviewPlan(
        nodes=[
            InterviewPlanNode(
                node_id=kind,
                kind=kind,
                goal=goal,
                project_fact_ids=[],
                required_targets=list(targets),
                opening_question=question.format(project=project),
                rubric_ids=["correctness", "mechanism", "scenario", "engineering"],
                max_followups=MAX_FOLLOWUPS_PER_NODE,
            )
            for kind, goal, question, targets in _FALLBACK_NODE_SPECS
        ]
    )


def fallback_interviewer_turn(state: Mapping) -> dict:
    """Ask the current node's safe opening question without model output."""

    node = _current_node(state)
    return {
        "question": str(node.get("opening_question") or "请继续介绍这个项目。")[:150],
        "kind": "opening" if not state.get("last_answer") else "clarification",
        "rationale": "模型暂不可用，使用节点保底问题",
        "referenced_quote": "",
        "followups_used": 0,
    }


def fallback_evidence_verification(state: Mapping) -> EvidenceVerification:
    """Keep the answer unverified rather than inventing coverage on failure."""

    node = state.get("current_node")
    required_targets = state.get("required_targets")
    if not isinstance(required_targets, list) and isinstance(node, Mapping):
        required_targets = node.get("required_targets")
    missing = [str(item) for item in required_targets or [] if str(item).strip()]
    return EvidenceVerification(
        claims=[],
        covered_targets=[],
        missing_targets=missing,
        conflicts=[],
        confidence=0,
        route="insufficient",
    )


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

    def emit(state: InterviewGraphState, event_kind: str, graph_step_id: str, payload: dict) -> dict:
        event = {
            "session_id": str(state.get("session_id", "")),
            "graph_step_id": graph_step_id,
            "event_kind": event_kind,
            "payload": payload,
        }
        if event_sink is not None:
            event_sink(event)
        return event

    def planner(state: InterviewGraphState) -> dict:
        plan = state.get("plan", [])
        degraded = False
        plan_method = getattr(agents, "plan", None)
        if callable(plan_method):
            try:
                result = plan_method(state)
                plan = InterviewPlan.model_validate({"nodes": _dump(result).get("nodes", [])}).model_dump(
                    mode="json"
                )["nodes"]
            except Exception as error:
                if not _is_model_failure(error):
                    raise
                plan = []
                degraded = True
        if not plan:
            plan = fallback_interview_plan(state).model_dump(mode="json")["nodes"]
            degraded = True
        updates = {"plan": plan, "current_node_index": 0, "status": "planning"}
        if degraded:
            updates["graph_events"] = [
                emit(
                    state,
                    "state_updated",
                    "degraded:planner",
                    {"status": "planning", "degraded": True, "role": "planner"},
                )
            ]
        return updates

    def interviewer(state: InterviewGraphState) -> dict:
        node = _current_node(state)
        ask_method = getattr(agents, "ask", None)
        degraded = False
        try:
            turn = _dump(ask_method(state)) if callable(ask_method) else fallback_interviewer_turn(state)
        except Exception as error:
            if not _is_model_failure(error):
                raise
            turn = fallback_interviewer_turn(state)
            degraded = True
        text = str(turn.get("question", node.get("opening_question", "请继续介绍。")))
        question_kind = str(turn.get("kind", "followup" if state.get("last_answer") else "opening"))

        question = {"node_id": str(node.get("node_id", "unknown")), "text": text, "kind": question_kind}
        current_question_id = question_id(state)
        event = emit(
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
        updates = {
            "current_question": question,
            "messages": [message],
            "graph_events": [event],
            "status": "awaiting_answer",
        }
        if degraded:
            updates["graph_events"].append(
                emit(
                    state,
                    "state_updated",
                    f"degraded:interviewer:{current_question_id}",
                    {"status": "awaiting_answer", "degraded": True, "role": "interviewer"},
                )
            )
        return updates

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
        event = emit(
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
            "graph_events": [event],
            "status": "verifying",
        }

    def evidence_verifier(state: InterviewGraphState) -> dict:
        verify_method = getattr(agents, "verify", None)
        degraded = False
        try:
            verification = (
                EvidenceVerification.model_validate(_dump(verify_method(state)))
                if callable(verify_method)
                else fallback_evidence_verification(state)
            )
        except Exception as error:
            if not _is_model_failure(error):
                raise
            verification = fallback_evidence_verification(state)
            degraded = True

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

        updates = {
            "route": verification.route,
            "coverage": coverage,
            "conflicts": conflicts,
            "followups_used": followups_used,
            "status": "verifying",
        }
        if degraded or not callable(verify_method):
            updates["graph_events"] = [
                emit(
                    state,
                    "state_updated",
                    f"degraded:verifier:{question_id(state)}",
                    {"status": "verifying", "degraded": True, "role": "evidence_verifier"},
                )
            ]
        return updates

    def advance_plan(state: InterviewGraphState) -> dict:
        return {
            "current_node_index": state.get("current_node_index", 0) + 1,
            "current_question": None,
            "last_answer": None,
            "route": "covered",
            "status": "planning",
        }

    def wrap_up(state: InterviewGraphState) -> dict:
        plan = state.get("plan", [])
        event = emit(
            state,
            "completed",
            "completed",
            {
                "status": "completed",
                "current_question_index": len(plan),
                "total_questions": len(plan),
            },
        )
        return {
            "route": "completed",
            "status": "completed",
            "current_question": None,
            "graph_events": [event],
        }

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
