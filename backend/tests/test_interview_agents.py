import json

import httpx
import pytest
from pydantic import ValidationError

from app.interview_agents import (
    parse_evidence_verification,
    parse_interview_plan,
    parse_interviewer_turn,
)
from app.prompts import build_interviewer_prompt, build_planner_prompt, build_verifier_prompt


def project_context():
    return {
        "project": {"project_id": "p1", "name": "Echo Offer", "summary": "AI 模拟面试"},
        "verified_facts": [{"fact_id": "f1", "summary": "使用 LangGraph", "source": "resume"}],
        "target_role": "Agent 工程师",
        "capability_summary": "熟悉 Python 和 RAG",
    }


def test_planner_prompt_forbids_unverified_facts_and_grades():
    system, user = build_planner_prompt(project_context())
    assert "未验证事实" in system
    assert "不得评分" in system
    assert "context_ownership" in user
    assert "verified_facts" in user


def test_interviewer_prompt_contains_only_recent_context():
    context = {
        "current_node": {"node_id": "node-1", "kind": "architecture", "goal": "确认架构"},
        "last_answer": {"node_id": "node-1", "content": "我用了队列"},
        "verifier_result": {"route": "insufficient", "missing_targets": ["failure"]},
        "messages": [{"role": "candidate", "content": f"回答 {index}"} for index in range(8)],
    }
    _, user = build_interviewer_prompt(context)
    assert "回答 1" not in user
    assert "回答 7" in user


def test_interviewer_must_reference_last_answer_for_followup():
    with pytest.raises(ValueError, match="last answer reference"):
        parse_interviewer_turn(
            '{"question":"泛化问题", "kind":"followup", "referenced_quote":""}'
        )


def test_interviewer_rejects_unknown_kind_and_ungrounded_reference():
    with pytest.raises(ValueError, match="unsupported interviewer kind"):
        parse_interviewer_turn(
            '{"question":"问题", "kind":"probe", "referenced_quote":"回答"}'
        )
    with pytest.raises(ValueError, match="referenced quote must come from last answer"):
        parse_interviewer_turn(
            '{"question":"怎么验证？", "kind":"followup", "referenced_quote":"模型很快"}',
            last_answer="我们通过缓存降低了延迟。",
        )
    parsed = parse_interviewer_turn(
        '{"question":"怎么验证？", "kind":"followup", "referenced_quote":"缓存降低了延迟"}',
        last_answer="我们通过缓存降低了延迟。",
    )
    assert parsed.referenced_quote == "缓存降低了延迟"


def test_verifier_rejects_unknown_route_and_plan_parser_limits_text():
    with pytest.raises(ValidationError):
        parse_evidence_verification(
            json.dumps(
                {
                    "claims": [],
                    "covered_targets": [],
                    "missing_targets": [],
                    "conflicts": [],
                    "confidence": 0.8,
                    "route": "free_form_node",
                }
            )
        )

    nodes = [
        {
            "node_id": f"node-{index}",
            "kind": kind,
            "goal": "目标" * 500,
            "project_fact_ids": [],
            "required_targets": [kind],
            "opening_question": "问题" * 500,
            "rubric_ids": [],
            "max_followups": 2,
        }
        for index, kind in enumerate(
            ["opening", "project", "architecture", "challenge", "tradeoff", "evidence"]
        )
    ]
    plan = parse_interview_plan(json.dumps({"nodes": nodes}, ensure_ascii=False))
    assert len(plan.nodes[0].goal) <= 500
    assert len(plan.nodes[0].opening_question) <= 150


def test_interview_agents_use_role_specific_call_kinds():
    from app.interview_agents import SiliconFlowInterviewAgents
    from app.llm_observability import capture_model_calls
    from app.model_settings import ModelSettingsValues

    responses = [
        {
            "nodes": [
                {
                    "node_id": f"node-{index}",
                    "kind": kind,
                    "goal": "目标",
                    "project_fact_ids": [],
                    "required_targets": [kind],
                    "opening_question": "请继续介绍。",
                    "rubric_ids": [],
                    "max_followups": 2,
                }
                for index, kind in enumerate(
                    ["opening", "project", "architecture", "challenge", "tradeoff", "evidence"]
                )
            ]
        },
        {"question": "继续说明", "kind": "opening", "referenced_quote": ""},
        {
            "claims": [],
            "covered_targets": [],
            "missing_targets": [],
            "conflicts": [],
            "confidence": 0.8,
            "route": "covered",
        },
    ]

    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(responses.pop(0), ensure_ascii=False)}}]},
        )

    settings = ModelSettingsValues(
        base_url="https://example.test/v1",
        model="test-model",
        assessment_model="test-model",
        api_key="test-key",
        temperature=0.1,
        max_tokens=3200,
        timeout_seconds=10,
        assessment_batch_size=1,
    )
    agents = SiliconFlowInterviewAgents(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    graph_node = {
        "node_id": "node-0",
        "kind": "opening",
        "goal": "确认职责",
        "project_fact_ids": [],
        "required_targets": ["context_ownership"],
        "opening_question": "你负责什么？",
        "rubric_ids": [],
        "max_followups": 2,
    }
    graph_state = {
        "plan": [graph_node],
        "current_node_index": 0,
        "last_answer": {"node_id": "node-0", "content": "我负责后端"},
        "current_question": {"node_id": "node-0", "text": "你负责什么？", "kind": "opening"},
        "verified_facts": [{"fact_id": "f1", "summary": "使用 LangGraph", "source": "resume"}],
        "route": "insufficient",
        "missing_targets": ["context_ownership"],
        "messages": [],
    }

    with capture_model_calls("trace-1") as capture:
        agents.plan(project_context())
        agents.ask(graph_state)
        agents.verify(graph_state)

    assert [record.call_kind for record in capture.records] == ["planner", "interviewer", "evidence_verifier"]
    assert "node-0" in json.dumps(requests[1], ensure_ascii=False)
    assert "我负责后端" in json.dumps(requests[1], ensure_ascii=False)
    assert "context_ownership" in json.dumps(requests[2], ensure_ascii=False)


def test_interview_agents_require_api_key_before_request():
    from app.interview_agents import SiliconFlowInterviewAgents
    from app.model_settings import ModelSettingsValues
    from app.providers import AssessmentProviderError

    settings = ModelSettingsValues(
        base_url="https://example.test/v1",
        model="test-model",
        assessment_model="test-model",
        api_key="",
        temperature=0.1,
        max_tokens=3200,
        timeout_seconds=10,
        assessment_batch_size=1,
    )

    with pytest.raises(AssessmentProviderError) as error:
        SiliconFlowInterviewAgents(settings).plan(project_context())
    assert error.value.code == "provider_not_configured"
