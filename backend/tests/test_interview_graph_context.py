import json
from types import SimpleNamespace

import pytest

from app.interview_graph_api import _initial_state, build_graph_context


def _project() -> SimpleNamespace:
    return SimpleNamespace(
        id="project-1",
        project_name="企业知识库 Agent",
        background_goal="降低内部知识检索成本",
        tech_stack="Python、FastAPI、Milvus",
        responsibilities="负责检索链路和线上监控",
        core_solution="查询改写、混合检索、重排",
        engineering_challenges="召回质量和延迟平衡",
        failure_improvements="增加超时、降级和评估集",
        quantified_results="P95 下降 20%",
    )


def test_graph_context_keeps_only_confirmed_project_facts():
    analysis = SimpleNamespace(
        status="confirmed",
        analysis_json=json.dumps(
            {
                "facts": [
                    {"fact_id": "f1", "field": "latency", "value": "P95 降低 20%", "status": "extracted"},
                    {"fact_id": "f2", "field": "guess", "value": "不可作为前提", "status": "inferred"},
                    {"fact_id": "f3", "field": "rejected", "value": "不应进入上下文", "status": "rejected"},
                ],
                "resume_text": "这段简历原文不能进入 Graph State",
                "api_key": "secret-key",
            },
            ensure_ascii=False,
        ),
    )

    context = build_graph_context(_project(), analysis)
    serialized = json.dumps(context, ensure_ascii=False)

    assert context["verified_facts"] == [
        {"fact_id": "f1", "field": "latency", "value": "P95 降低 20%"}
    ]
    assert "简历原文" not in serialized
    assert "api_key" not in serialized
    assert context["project"]["name"] == "企业知识库 Agent"


def test_graph_context_falls_back_to_confirmed_project_fields():
    context = build_graph_context(_project(), None)

    assert context["project"]["name"] == "企业知识库 Agent"
    assert {fact["fact_id"] for fact in context["verified_facts"]} >= {
        "project:tech_stack",
        "project:responsibilities",
        "project:quantified_results",
    }


def test_initial_graph_state_contains_hydrated_context():
    session = SimpleNamespace(id="session-1")
    state = _initial_state(session, _project(), None)

    assert state["project"]["name"] == "企业知识库 Agent"
    assert state["verified_facts"]


@pytest.mark.parametrize("status", ["draft", "failed"])
def test_graph_context_ignores_non_confirmed_analysis(status):
    analysis = SimpleNamespace(
        status=status,
        analysis_json=json.dumps(
            {"facts": [{"fact_id": "f1", "field": "x", "value": "y", "status": "confirmed"}]}
        ),
    )

    context = build_graph_context(_project(), analysis)

    assert all(fact["fact_id"] != "f1" for fact in context["verified_facts"])
