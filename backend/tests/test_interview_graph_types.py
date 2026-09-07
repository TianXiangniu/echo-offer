import json

import pytest
from pydantic import ValidationError

from app.interview_graph_types import (
    EvidenceVerification,
    InterviewGraphStatePayload,
    InterviewPlan,
    InterviewPlanNode,
    InterviewerTurn,
    MAX_FOLLOWUPS_PER_NODE,
    REQUIRED_PLAN_KINDS,
)


def valid_plan_payload():
    return {
        "nodes": [
            {
                "node_id": "plan-1",
                "kind": "opening",
                "goal": "建立面试上下文",
                "project_fact_ids": ["fact-1"],
                "required_targets": ["self_intro"],
                "opening_question": "先做个简短自我介绍。",
                "rubric_ids": ["rubric-1"],
                "max_followups": 2,
            },
            {
                "node_id": "plan-2",
                "kind": "project",
                "goal": "确认项目背景",
                "project_fact_ids": ["fact-2"],
                "required_targets": ["project_scope"],
                "opening_question": "这个项目的背景是什么？",
                "rubric_ids": ["rubric-2"],
                "max_followups": 2,
            },
            {
                "node_id": "plan-3",
                "kind": "architecture",
                "goal": "确认架构设计",
                "project_fact_ids": ["fact-3"],
                "required_targets": ["architecture"],
                "opening_question": "你是怎么设计整体架构的？",
                "rubric_ids": ["rubric-3"],
                "max_followups": 2,
            },
            {
                "node_id": "plan-4",
                "kind": "challenge",
                "goal": "确认关键难点",
                "project_fact_ids": ["fact-4"],
                "required_targets": ["challenge"],
                "opening_question": "最大的技术难点是什么？",
                "rubric_ids": ["rubric-4"],
                "max_followups": 2,
            },
            {
                "node_id": "plan-5",
                "kind": "tradeoff",
                "goal": "确认方案取舍",
                "project_fact_ids": ["fact-5"],
                "required_targets": ["tradeoff"],
                "opening_question": "为什么这么取舍？",
                "rubric_ids": ["rubric-5"],
                "max_followups": 2,
            },
            {
                "node_id": "plan-6",
                "kind": "evidence",
                "goal": "确认结果与证据",
                "project_fact_ids": ["fact-6"],
                "required_targets": ["evidence"],
                "opening_question": "你怎么验证结果有效？",
                "rubric_ids": ["rubric-6"],
                "max_followups": 2,
            },
        ]
    }


def valid_verifier_payload():
    return {
        "claims": ["claim-1"],
        "covered_targets": ["target-1"],
        "missing_targets": [],
        "conflicts": [],
        "confidence": 0.8,
        "route": "covered",
    }


def valid_graph_state_payload():
    return {
        "session_id": "session-1",
        "project": {
            "project_id": "project-1",
            "name": "Echo Offer",
            "summary": "面向求职者的 AI 模拟面试系统。",
        },
        "verified_facts": [
            {
                "fact_id": "fact-1",
                "summary": "使用 LangGraph 编排面试流程。",
                "source": "resume",
            }
        ],
        "plan": valid_plan_payload()["nodes"],
        "current_node_index": 0,
        "current_question": {
            "node_id": "plan-1",
            "text": "先做个简短自我介绍。",
            "kind": "opening",
        },
        "messages": [
            {
                "role": "interviewer",
                "node_id": "plan-1",
                "content": "先做个简短自我介绍。",
            }
        ],
        "last_answer": None,
        "coverage": {"plan-1": ["self_intro"]},
        "conflicts": [],
        "followups_used": {"plan-1": 0},
        "route": "covered",
        "status": "awaiting_answer",
        "error": None,
    }


def test_plan_requires_six_unique_nodes_and_core_dimensions():
    payload = valid_plan_payload()
    payload["nodes"] = payload["nodes"][:5]

    with pytest.raises(ValidationError):
        InterviewPlan.model_validate(payload)


def test_verifier_route_is_closed_enum():
    with pytest.raises(ValidationError):
        EvidenceVerification.model_validate(
            {
                "claims": [],
                "covered_targets": [],
                "missing_targets": [],
                "conflicts": [],
                "confidence": 0.8,
                "route": "free_form_node",
            }
        )


def test_plan_rejects_duplicate_node_ids_and_invalid_followup_caps():
    payload = valid_plan_payload()
    payload["nodes"][1]["node_id"] = payload["nodes"][0]["node_id"]
    payload["nodes"][0]["max_followups"] = MAX_FOLLOWUPS_PER_NODE + 1

    with pytest.raises(ValidationError):
        InterviewPlan.model_validate(payload)


def test_plan_requires_all_core_kinds():
    payload = valid_plan_payload()
    payload["nodes"][0]["kind"] = "project"

    with pytest.raises(ValidationError):
        InterviewPlan.model_validate(payload)


def test_types_are_json_serializable():
    plan = InterviewPlan.model_validate(valid_plan_payload())
    verifier = EvidenceVerification.model_validate(valid_verifier_payload())
    turn = InterviewerTurn(
        question="先介绍一下你自己。",
        rationale="opening",
        followups_used=1,
    )

    payload = {
        "state": {
            "session_id": "session-1",
            "profile_id": "profile-1",
            "selected_project_id": "project-1",
        },
        "plan": plan.model_dump(),
        "verifier": verifier.model_dump(),
        "turn": turn.model_dump(),
    }

    assert json.loads(json.dumps(payload, ensure_ascii=False))
    assert REQUIRED_PLAN_KINDS == {
        "opening",
        "project",
        "architecture",
        "challenge",
        "tradeoff",
        "evidence",
    }


@pytest.mark.parametrize(
    ("container", "unsafe_key"),
    [
        ("state", "api_key"),
        ("project", "resume_text"),
        ("question", "raw_model_response"),
        ("message", "chain_of_thought"),
    ],
)
def test_graph_state_validates_a_complete_safe_json_payload(container, unsafe_key):
    payload = valid_graph_state_payload()
    state = InterviewGraphStatePayload.model_validate(payload)

    assert json.loads(json.dumps(state.model_dump(mode="json"), ensure_ascii=False)) == payload

    containers = {
        "state": payload,
        "project": payload["project"],
        "question": payload["current_question"],
        "message": payload["messages"][0],
    }
    containers[container][unsafe_key] = "unsafe"
    with pytest.raises(ValidationError):
        InterviewGraphStatePayload.model_validate(payload)


def test_graph_state_rejects_followups_above_the_node_cap():
    payload = valid_graph_state_payload()
    payload["followups_used"]["plan-1"] = MAX_FOLLOWUPS_PER_NODE + 1

    with pytest.raises(ValidationError):
        InterviewGraphStatePayload.model_validate(payload)


def test_graph_state_rejects_a_plan_without_six_nodes():
    payload = valid_graph_state_payload()
    payload["plan"] = payload["plan"][:1]

    with pytest.raises(ValidationError):
        InterviewGraphStatePayload.model_validate(payload)


def test_graph_state_rejects_duplicate_plan_node_ids():
    payload = valid_graph_state_payload()
    payload["plan"][1]["node_id"] = payload["plan"][0]["node_id"]

    with pytest.raises(ValidationError):
        InterviewGraphStatePayload.model_validate(payload)


def test_graph_state_rejects_plan_with_a_missing_required_kind():
    payload = valid_graph_state_payload()
    payload["plan"][0]["kind"] = "project"

    with pytest.raises(ValidationError):
        InterviewGraphStatePayload.model_validate(payload)
