from langgraph.types import Command

from app.interview_graph import (
    build_interview_graph,
    fallback_evidence_verification,
    fallback_interview_plan,
)
from app.interview_graph_runtime import close_checkpointer, create_checkpointer, graph_config
from app.providers import AssessmentProviderError
from app.interview_graph_types import REQUIRED_PLAN_KINDS


def test_planner_failure_still_returns_six_node_plan():
    plan = fallback_interview_plan(
        {"project": {"name": "RAG Agent"}, "verified_facts": []}
    )

    assert len(plan.nodes) == 6
    assert {node.kind for node in plan.nodes} == REQUIRED_PLAN_KINDS
    assert all(node.project_fact_ids == [] for node in plan.nodes)
    assert "RAG Agent" in plan.nodes[0].opening_question


def test_fallback_questions_use_conversational_words():
    plan = fallback_interview_plan({"project": {"name": "RAG Agent"}})

    spoken_questions = [node.opening_question for node in plan.nodes]

    assert not any(
        term in question
        for question in spoken_questions
        for term in ("业务目标", "个人职责", "团队边界")
    )
    assert "为什么要做" in spoken_questions[0]
    assert "主要负责哪一块" in spoken_questions[0]


def test_verifier_failure_does_not_claim_coverage():
    result = fallback_evidence_verification(
        {"required_targets": ["指标"], "current_node": {"required_targets": ["指标"]}}
    )

    assert result.route == "insufficient"
    assert result.confidence == 0
    assert result.claims == []
    assert result.covered_targets == []
    assert result.missing_targets == ["指标"]


class ProviderUnavailableAgents:
    def _error(self):
        raise AssessmentProviderError("provider_not_configured", "模型服务尚未配置")

    def plan(self, state):
        self._error()

    def ask(self, state):
        self._error()

    def verify(self, state):
        self._error()


def _initial_state():
    return {
        "session_id": "fallback-session",
        "project": {"project_id": "p1", "name": "RAG Agent", "summary": "检索项目"},
        "verified_facts": [],
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


def test_provider_errors_degrade_to_a_question_and_safe_events(tmp_path):
    events = []
    checkpointer = create_checkpointer(str(tmp_path / "fallback.sqlite"))
    try:
        graph = build_interview_graph(
            ProviderUnavailableAgents(), checkpointer, event_sink=events.append
        )
        config = graph_config("fallback-session")
        first = graph.invoke(_initial_state(), config)
        assert "__interrupt__" in first
        assert graph.get_state(config).values["current_question"]["text"]
        assert any(
            event["event_kind"] == "state_updated"
            and event["payload"].get("degraded") is True
            for event in events
        )

        resumed = graph.invoke(Command(resume="补充回答"), config)
        assert "__interrupt__" in resumed
        assert any(
            event["payload"].get("role") == "evidence_verifier"
            for event in events
            if event["event_kind"] == "state_updated"
        )
    finally:
        close_checkpointer(checkpointer)
