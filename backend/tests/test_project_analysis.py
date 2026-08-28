import pytest
from pydantic import ValidationError

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
