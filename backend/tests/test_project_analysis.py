import asyncio
import json
import hashlib

import httpx
import pymupdf
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models import Resume, ResumeProject, ResumeProjectAnalysis, ResumeProjectQuestion
from app.project_analysis import clean_model_json, parse_model_analysis, validate_analysis_evidence
from app.providers import ProjectAnalysisProviderError, SiliconFlowProjectAnalysisProvider
from app.schemas import AgentProjectAnalysisResponse
from app.services import stream_resume_project_analysis


def make_pdf_bytes():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(72, 72, 520, 180),
        "Project experience: built a retrieval augmented generation agent.",
    )
    try:
        return document.tobytes()
    finally:
        document.close()


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


def test_parse_model_analysis_normalizes_common_deepseek_shape_variants():
    payload = valid_analysis_payload()
    payload["project"]["tech_stack"] = ["Python", "FastAPI"]
    payload["project"]["responsibilities"] = ["负责后端", "负责评估"]
    payload["project"]["engineering_challenges"] = ["召回质量", "响应延迟"]
    payload.pop("selection_reason")
    payload.pop("confidence")
    payload["evidence"] = payload["evidence"][0]
    payload["evidence"].pop("field")
    payload["evidence"]["quote"] = "负责后端"
    payload["questions"] = [question["prompt"] for question in payload["questions"]]

    result = parse_model_analysis(json.dumps(payload, ensure_ascii=False))

    assert result.project.tech_stack == "Python；FastAPI"
    assert result.project.responsibilities == "负责后端；负责评估"
    assert result.project.engineering_challenges == "召回质量；响应延迟"
    assert result.selection_reason
    assert result.confidence == 0
    assert len(result.evidence) == 1
    assert result.evidence[0].field == "responsibilities"
    assert [question.knowledge_point_id for question in result.questions] == [
        "project.ownership_and_context",
        "project.architecture_tradeoffs",
        "project.evaluation_and_reproducibility",
    ]


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


def test_siliconflow_provider_uses_timeout_safe_generation_options():
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

    provider.analyze("简历文本")

    payload = json.loads(requests[0].content)
    assert payload["max_tokens"] == 2400
    assert payload["thinking_budget"] == 256
    assert payload["reasoning_effort"] == "high"
    assert "response_format" not in payload


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


class FakeProjectAnalysisProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def analyze(self, resume_text):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_analysis_endpoint_saves_draft_and_calls_provider_once(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    provider = FakeProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    )
    client.app.state.project_analysis_provider = provider

    response = client.post(
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis",
        json={"resume_text": "负责检索链路和线上监控"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert len(response.json()["questions"]) == 3
    assert provider.calls == 1


def test_missing_resume_does_not_call_provider(client):
    provider = FakeProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    )
    client.app.state.project_analysis_provider = provider

    response = client.post(
        "/api/resumes/not-found/agent-project-analysis",
        json={"resume_text": "简历文本"},
    )

    assert response.status_code == 404
    assert provider.calls == 0


def test_provider_failure_returns_stable_error(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    client.app.state.project_analysis_provider = FakeProjectAnalysisProvider(
        error=ProjectAnalysisProviderError("provider_timeout", "模型请求超时")
    )

    response = client.post(
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis",
        json={"resume_text": "简历文本"},
    )

    assert response.status_code == 504
    assert response.json()["code"] == "provider_timeout"


def test_confirmed_analysis_saves_edited_project_and_questions(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    result = AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    client.app.state.project_analysis_provider = FakeProjectAnalysisProvider(result=result)

    analysis = client.post(
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis",
        json={"resume_text": "负责检索链路和线上监控"},
    ).json()
    project = result.project.model_dump()
    questions = [question.model_dump() for question in result.questions]
    questions[0]["prompt"] = "请详细说明你亲自负责的检索链路。"

    profile = client.post(
        "/api/profile",
        json={
            "resume_id": parsed["resume_id"],
            "resume_text": "负责检索链路和线上监控；用户确认补充了故障复盘。",
            "analysis_id": analysis["analysis_id"],
            "project": project,
            "project_questions": questions,
        },
    )

    assert profile.status_code == 200
    with client.app.state.session_factory() as db:
        saved_project = db.get(ResumeProject, profile.json()["profile_id"])
        saved_questions = list(
            db.scalars(
                select(ResumeProjectQuestion)
                .where(ResumeProjectQuestion.resume_project_id == saved_project.id)
                .order_by(ResumeProjectQuestion.order)
            )
        )
        saved_analysis = db.get(ResumeProjectAnalysis, analysis["analysis_id"])
        assert saved_project.analysis_id == analysis["analysis_id"]
        assert saved_questions[0].source == "user_edited"
        assert saved_analysis.status == "confirmed"


def test_invalid_analysis_evidence_returns_stable_error(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    invalid = valid_analysis_payload()
    invalid["evidence"][0]["quote"] = "不存在于简历中的证据"
    client.app.state.project_analysis_provider = FakeProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(invalid)
    )

    response = client.post(
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis",
        json={"resume_text": "负责检索链路和线上监控"},
    )

    assert response.status_code == 502
    assert response.json()["code"] == "invalid_model_response"


def test_provider_not_configured_returns_503(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    client.app.state.project_analysis_provider = SiliconFlowProjectAnalysisProvider(
        api_key="",
        model="test-model",
        base_url="https://api.siliconflow.cn/v1",
        timeout_seconds=5,
    )

    response = client.post(
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis",
        json={"resume_text": "简历文本"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "provider_not_configured"


def test_text_changed_after_analysis_is_saved_with_final_hash(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    result = AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    client.app.state.project_analysis_provider = FakeProjectAnalysisProvider(result=result)
    analysis = client.post(
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis",
        json={"resume_text": "负责检索链路和线上监控"},
    ).json()
    final_text = "负责检索链路和线上监控；用户补充了故障复盘。"

    response = client.post(
        "/api/profile",
        json={
            "resume_id": parsed["resume_id"],
            "resume_text": final_text,
            "analysis_id": analysis["analysis_id"],
            "project": result.project.model_dump(),
            "project_questions": [question.model_dump() for question in result.questions],
        },
    )

    assert response.status_code == 200
    with client.app.state.session_factory() as db:
        saved_project = db.get(ResumeProject, response.json()["profile_id"])
        saved_resume = db.get(Resume, parsed["resume_id"])
        assert saved_project is not None
        assert saved_resume.text_hash == hashlib.sha256(final_text.encode("utf-8")).hexdigest()


async def collect_events(generator):
    return [event async for event in generator]


def event_type(event: str) -> str:
    return event.splitlines()[0].removeprefix("event: ")


def event_data(event: str) -> dict:
    return json.loads(event.splitlines()[1].removeprefix("data: "))


def test_stream_resume_project_analysis_emits_ordered_events_and_result(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    provider = FakeProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    )
    db = client.app.state.session_factory()
    try:
        events = asyncio.run(
            collect_events(
                stream_resume_project_analysis(
                    db, provider, parsed["resume_id"], "负责检索链路和线上监控"
                )
            )
        )
    finally:
        db.close()

    assert [event_type(event) for event in events] == [
        "stage", "stage", "stage", "stage", "result", "done"
    ]
    assert event_data(events[0])["stage"] == "received"
    assert event_data(events[1])["stage"] == "analyzing"
    assert event_data(events[2])["stage"] == "validating"
    assert event_data(events[3])["stage"] == "completed"
    assert event_data(events[-1])["status"] == "completed"
    assert event_data(events[-2])["status"] == "draft"


class SlowProjectAnalysisProvider(FakeProjectAnalysisProvider):
    def analyze(self, resume_text):
        import time

        time.sleep(0.03)
        return super().analyze(resume_text)


def test_stream_resume_project_analysis_emits_heartbeat_while_provider_runs(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    provider = SlowProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    )
    db = client.app.state.session_factory()
    try:
        events = asyncio.run(
            collect_events(
                stream_resume_project_analysis(
                    db,
                    provider,
                    parsed["resume_id"],
                    "负责检索链路和线上监控",
                    heartbeat_interval_seconds=0.01,
                )
            )
        )
    finally:
        db.close()

    assert any(event_type(event) == "heartbeat" for event in events)
    assert event_type(events[-1]) == "done"


def test_stream_resume_project_analysis_emits_error_without_result(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    provider = FakeProjectAnalysisProvider(
        error=ProjectAnalysisProviderError("provider_timeout", "模型请求超时")
    )
    db = client.app.state.session_factory()
    try:
        events = asyncio.run(
            collect_events(
                stream_resume_project_analysis(
                    db, provider, parsed["resume_id"], "负责检索链路和线上监控"
                )
            )
        )
    finally:
        db.close()

    assert event_type(events[-1]) == "error"
    assert event_data(events[-1])["code"] == "provider_timeout"
    assert not any(event_type(event) == "result" for event in events)
    assert not any(event_type(event) == "done" for event in events)
