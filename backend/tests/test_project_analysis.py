import json

import httpx
import pytest
from pydantic import ValidationError

from app.project_analysis import clean_model_json, validate_analysis_evidence
from app.providers import ProjectAnalysisProviderError, SiliconFlowProjectAnalysisProvider
from app.schemas import AgentProjectAnalysisResponse


def valid_analysis_payload():
    return {
        "project": {
            "project_name": "企业知识库 Agent",
            "background_goal": "提升内部知识检索效率",
            "tech_stack": "Python、FastAPI、向量数据库",
            "responsibilities": "负责检索链路和线上监控",
            "core_solution": "查询改写、混合检索、重排",
            "engineering_challenges": "召回质量和延迟平衡",
            "failure_improvements": "增加评估集和降级",
            "quantified_results": "",
        },
        "selection_reason": "该项目包含 Agent 检索链路和线上工程信息。",
        "confidence": 0.86,
        "evidence": [
            {"field": "responsibilities", "quote": "负责检索链路和线上监控"}
        ],
        "questions": [
            {
                "prompt": "你在这个项目中具体负责了哪些检索链路？",
                "knowledge_point_id": "project.ownership_and_context",
                "signals": ["个人职责", "检索链路"],
            },
            {
                "prompt": "为什么选择查询改写、混合检索和重排的组合？",
                "knowledge_point_id": "project.architecture_tradeoffs",
                "signals": ["方案", "取舍"],
            },
            {
                "prompt": "你如何验证召回质量和延迟改进是真实稳定的？",
                "knowledge_point_id": "project.evaluation_and_reproducibility",
                "signals": ["评估", "指标", "复现"],
            },
        ],
        "missing_information": ["缺少明确的线上流量规模"],
    }


def test_analysis_response_requires_exactly_three_questions():
    payload = valid_analysis_payload()
    payload["questions"] = payload["questions"][:2]

    with pytest.raises(ValidationError):
        AgentProjectAnalysisResponse.model_validate(payload)


def test_analysis_response_allows_missing_quantified_result():
    result = AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())

    assert result.project.quantified_results == ""
    assert result.questions[0].knowledge_point_id.startswith("project.")


def test_clean_model_json_removes_markdown_fence():
    fence = chr(96) * 3

    assert clean_model_json(fence + "json\n{\"ok\": true}\n" + fence) == '{"ok": true}'


def test_evidence_must_exist_in_resume_text():
    result = AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())

    validated = validate_analysis_evidence(
        result,
        "负责检索链路和线上监控；项目使用查询改写、混合检索和重排。",
    )

    assert validated.evidence[0].quote == "负责检索链路和线上监控"


def test_siliconflow_provider_reads_content_from_chat_response():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(valid_analysis_payload(), ensure_ascii=False)
                        }
                    }
                ]
            },
        )

    provider = SiliconFlowProjectAnalysisProvider(
        api_key="test-only",
        model="test-model",
        base_url="https://api.siliconflow.cn/v1",
        timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.analyze("负责检索链路和线上监控")

    assert result.questions[0].knowledge_point_id.startswith("project.")
    assert requests[0].url.path == "/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer test-only"


def test_provider_maps_rate_limit_to_stable_error():
    provider = SiliconFlowProjectAnalysisProvider(
        api_key="test-only",
        model="test-model",
        base_url="https://api.siliconflow.cn/v1",
        timeout_seconds=5,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, json={"message": "limited"})
            )
        ),
    )

    with pytest.raises(ProjectAnalysisProviderError) as error:
        provider.analyze("简历文本")

    assert error.value.code == "provider_rate_limited"
