from pathlib import Path

import pytest
from langgraph.types import Command

from app.interview_graph_runtime import close_checkpointer, create_checkpointer, graph_config
from app.interview_graph_types import EvidenceVerification, InterviewPlan, InterviewPlanNode, InterviewerTurn
from app.interview_graph import build_interview_graph, route_after_verification


def valid_plan() -> InterviewPlan:
    kinds = ["opening", "project", "architecture", "challenge", "tradeoff", "evidence"]
    return InterviewPlan(
        nodes=[
            InterviewPlanNode(
                node_id=f"node-{index}",
                kind=kind,
                goal=f"验证 {kind}",
                project_fact_ids=[],
                required_targets=[kind],
                opening_question=f"请介绍 {kind}。",
                rubric_ids=[f"rubric-{index}"],
                max_followups=2,
            )
            for index, kind in enumerate(kinds)
        ]
    )


def graph_state(*, route: str, followups_used: dict[str, int], current_node_index: int = 2) -> dict:
    plan = valid_plan().model_dump()
    return {
        "session_id": "session-1",
        "project": {"project_id": "project-1", "name": "Echo Offer", "summary": "模拟面试系统"},
        "verified_facts": [],
        "plan": plan["nodes"],
        "current_node_index": current_node_index,
        "current_question": None,
        "messages": [],
        "last_answer": None,
        "coverage": {},
        "conflicts": [],
        "followups_used": followups_used,
        "route": route,
        "status": "verifying",
        "error": None,
    }


@pytest.mark.parametrize(
    ("route", "used", "current_node_index", "expected"),
    [
        ("conflict", 0, 2, "ask"),
        ("insufficient", 0, 2, "ask"),
        ("insufficient", 2, 2, "advance"),
        ("covered", 0, 2, "advance"),
        ("covered", 0, 5, "wrap_up"),
    ],
)
def test_verifier_route_is_deterministic(route, used, current_node_index, expected):
    state = graph_state(
        route=route,
        followups_used={"architecture": used},
        current_node_index=current_node_index,
    )
    assert route_after_verification(state) == expected


class FakeInterviewAgents:
    def plan(self, state):
        return valid_plan()

    def ask(self, state):
        node = state["plan"][state["current_node_index"]]
        return InterviewerTurn(
            question=node["opening_question"],
            rationale="按当前问题节点继续",
            followups_used=state["followups_used"].get(node["kind"], 0),
        )

    def verify(self, state):
        return EvidenceVerification(
            claims=[state["last_answer"]["content"]],
            covered_targets=[state["plan"][state["current_node_index"]]["kind"]],
            missing_targets=[],
            conflicts=[],
            confidence=0.9,
            route="covered",
        )

    def evaluate(self, state):
        return {"status": "evaluated"}

    def report(self, state):
        return {"status": "reported"}


def initial_state() -> dict:
    return graph_state(route="covered", followups_used={}, current_node_index=0) | {
        "plan": [],
        "status": "planning",
    }


def test_graph_exposes_explicit_nodes_and_resumes_after_checkpoint_reopen(tmp_path: Path):
    database_path = tmp_path / "interview-graph.sqlite"
    config = graph_config("session-graph")
    expected_nodes = {
        "load_context",
        "planner",
        "interviewer",
        "wait_for_candidate",
        "evidence_verifier",
        "advance_plan",
        "wrap_up",
        "finalize_transcript",
        "evaluator",
        "report",
    }

    first_checkpointer = create_checkpointer(str(database_path))
    try:
        first_graph = build_interview_graph(FakeInterviewAgents(), first_checkpointer)
        assert expected_nodes.issubset(first_graph.get_graph().nodes)
        interrupted = first_graph.invoke(initial_state(), config)
        assert "__interrupt__" in interrupted
    finally:
        close_checkpointer(first_checkpointer)

    second_checkpointer = create_checkpointer(str(database_path))
    try:
        resumed_graph = build_interview_graph(FakeInterviewAgents(), second_checkpointer)
        for index in range(6):
            result = resumed_graph.invoke(Command(resume=f"回答 {index}"), config)
            if index < 5:
                assert "__interrupt__" in result
            else:
                assert result["status"] == "completed"
                assert len(result["coverage"]) == 6
    finally:
        close_checkpointer(second_checkpointer)
