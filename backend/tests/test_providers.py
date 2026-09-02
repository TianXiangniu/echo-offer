import json

import httpx
import pytest

from app.providers import (
    AssessmentProviderError,
    BatchAssessmentCase,
    ProjectAnalysisProviderError,
    SiliconFlowAssessmentProvider,
    SiliconFlowProjectAnalysisProvider,
    probe_model_connection,
)
from app.model_settings import ModelSettingsValues
from app.question_bank import build_question_specs
from app.rubrics import build_rubric


ANSWER = "我的方案正确，解释机制，结合场景并说明工程边界。"


def valid_response():
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "items": [
                                {
                                    "rubric_id": item.rubric_id,
                                    "level": level,
                                    "evidence_start": 0,
                                    "evidence_end": len(ANSWER),
                                    "quoted_text": ANSWER,
                                    "confidence": 0.8,
                                }
                                for item, level in zip(
                                    build_rubric(build_question_specs()[0]).items,
                                    (3, 2, 3, 4),
                                    strict=True,
                                )
                            ]
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def mock_client(response_json=None, status_code=200, error=None, captured=None):
    def handler(request):
        if captured is not None:
            captured["json"] = json.loads(request.content)
        if error is not None:
            raise error
        return httpx.Response(status_code, json=response_json or valid_response())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_siliconflow_assessment_provider_parses_blind_rubric_response():
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(),
    )

    result = provider.assess(build_question_specs()[0], ANSWER, "submitted")

    assert result.evaluator == "siliconflow-blind-rubric-v1"
    assert result.level == 3
    assert len(result.rubric_items) == 4


def test_assessment_prompt_is_blind_to_resume_and_history():
    captured = {}
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(captured=captured),
    )

    provider.assess(build_question_specs()[0], ANSWER, "submitted")

    request_text = json.dumps(captured["json"], ensure_ascii=False)
    assert ANSWER in request_text
    assert "history" not in request_text.lower()
    assert "resume_text" not in request_text
    assert "过去分数" not in request_text
    assert "能力画像" not in request_text
    assert "综合分" not in request_text


@pytest.mark.parametrize("status_code", [401, 403])
def test_assessment_provider_maps_auth_errors(status_code):
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(status_code=status_code),
    )

    with pytest.raises(AssessmentProviderError, match="认证") as error:
        provider.assess(build_question_specs()[0], ANSWER, "submitted")
    assert error.value.code == "provider_auth_failed"


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(429, "provider_rate_limited"), (502, "provider_unavailable"), (503, "provider_unavailable"), (504, "provider_unavailable")],
)
def test_assessment_provider_maps_transient_http_errors(status_code, expected_code):
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(status_code=status_code),
    )

    with pytest.raises(AssessmentProviderError) as error:
        provider.assess(build_question_specs()[0], ANSWER, "submitted")
    assert error.value.code == expected_code


def test_assessment_provider_maps_timeout_and_connection_errors():
    timeout_provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(error=httpx.ReadTimeout("timeout")),
    )
    with pytest.raises(AssessmentProviderError) as timeout_error:
        timeout_provider.assess(build_question_specs()[0], ANSWER, "submitted")
    assert timeout_error.value.code == "provider_timeout"

    connection_provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(error=httpx.ConnectError("connection failed")),
    )
    with pytest.raises(AssessmentProviderError) as connection_error:
        connection_provider.assess(build_question_specs()[0], ANSWER, "submitted")
    assert connection_error.value.code == "provider_connection_failed"


def test_assessment_provider_rejects_malformed_model_response():
    malformed = {"choices": [{"message": {"content": "not json"}}]}
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(response_json=malformed),
    )

    with pytest.raises(AssessmentProviderError) as error:
        provider.assess(build_question_specs()[0], ANSWER, "submitted")
    assert error.value.code == "invalid_json"


def test_assessment_provider_reports_truncated_model_output():
    truncated = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": '{"items": ['},
            }
        ]
    }
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(response_json=truncated),
    )

    with pytest.raises(AssessmentProviderError) as error:
        provider.assess(build_question_specs()[0], ANSWER, "submitted")
    assert error.value.code == "provider_output_truncated"


def test_batch_assessment_provider_preserves_parser_error_code():
    malformed = {"choices": [{"message": {"content": "not json"}}]}
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=mock_client(response_json=malformed),
    )
    case = BatchAssessmentCase(
        answer_id="answer-1",
        question_id="question-1",
        question=build_question_specs()[0],
        answer_text=ANSWER,
    )

    with pytest.raises(AssessmentProviderError) as error:
        provider.assess_batch([case])

    assert error.value.code == "invalid_json"


def test_project_provider_uses_runtime_generation_settings():
    captured = {}
    provider = SiliconFlowProjectAnalysisProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=5,
        temperature=0.7,
        max_tokens=4800,
        client=mock_client(
            response_json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "project": {
                                        "project_name": "Agent",
                                        "background_goal": "检索",
                                        "tech_stack": "Python",
                                        "responsibilities": "后端",
                                        "core_solution": "RAG",
                                        "engineering_challenges": "延迟",
                                        "failure_improvements": "降级",
                                        "quantified_results": "",
                                    },
                                    "selection_reason": "项目相关",
                                    "confidence": 0.8,
                                    "evidence": [],
                                    "questions": [
                                        {
                                            "prompt": "你负责什么？",
                                            "knowledge_point_id": "project.ownership",
                                            "signals": ["职责", "贡献"],
                                        },
                                        {
                                            "prompt": "方案怎么选？",
                                            "knowledge_point_id": "project.tradeoff",
                                            "signals": ["方案", "取舍"],
                                        },
                                        {
                                            "prompt": "如何验证？",
                                            "knowledge_point_id": "project.evaluation",
                                            "signals": ["指标", "验证"],
                                        },
                                    ],
                                    "missing_information": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
            captured=captured,
        ),
    )

    provider.analyze("简历文本")

    assert captured["json"]["temperature"] == 0.7
    assert captured["json"]["max_tokens"] == 4800


def test_assessment_provider_uses_runtime_generation_settings():
    captured = {}
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=5,
        temperature=0.7,
        max_tokens=4800,
        client=mock_client(captured=captured),
    )

    provider.assess(build_question_specs()[0], ANSWER, "submitted")

    assert captured["json"]["temperature"] == 0.7
    assert captured["json"]["max_tokens"] == 4800


def test_batch_assessment_provider_uses_runtime_max_tokens():
    captured = {}
    case = BatchAssessmentCase(
        answer_id="answer-1",
        question_id="question-1",
        question=build_question_specs()[0],
        answer_text=ANSWER,
    )
    batch_items = [
        {
            "answer_id": case.answer_id,
            "question_id": case.question_id,
            "rubric_items": [
                {
                    "rubric_id": item.rubric_id,
                    "level": 3,
                    "quoted_text": ANSWER,
                    "confidence": 0.8,
                }
                for item in build_rubric(case.question).items
            ],
        }
    ]
    provider = SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=5,
        temperature=0.7,
        max_tokens=4800,
        client=mock_client(
            response_json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"items": batch_items})
                        }
                    }
                ]
            },
            captured=captured,
        ),
    )

    provider.assess_batch([case])

    assert captured["json"]["temperature"] == 0.7
    assert captured["json"]["max_tokens"] == 4800


def test_probe_model_connection_returns_redacted_success_metadata():
    captured = {}
    settings = ModelSettingsValues(
        base_url="https://example.test/v1",
        model="test-model",
        assessment_model="test-assessment-model",
        api_key="secret-key",
        temperature=0.7,
        max_tokens=4800,
        timeout_seconds=120,
        assessment_batch_size=2,
    )
    client = mock_client(
        response_json={
            "choices": [{"message": {"content": '{"ok": true}'}}]
        },
        captured=captured,
    )

    result = probe_model_connection(settings, client=client)

    assert result["ok"] is True
    assert result["model"] == "test-model"
    assert result["latency_ms"] >= 0
    assert "secret-key" not in json.dumps(result)
    assert captured["json"]["max_tokens"] == 16


def test_probe_model_connection_maps_missing_key_and_provider_errors():
    missing_key = ModelSettingsValues(
        base_url="https://example.test/v1",
        model="test-model",
        assessment_model="test-assessment-model",
        api_key="",
        temperature=0.1,
        max_tokens=3200,
        timeout_seconds=90,
        assessment_batch_size=3,
    )
    missing = probe_model_connection(missing_key)
    assert missing["ok"] is False
    assert missing["error_code"] == "provider_not_configured"

    auth_settings = ModelSettingsValues(
        base_url="https://example.test/v1",
        model="test-model",
        assessment_model="test-assessment-model",
        api_key="test-key",
        temperature=0.1,
        max_tokens=3200,
        timeout_seconds=90,
        assessment_batch_size=3,
    )
    auth_result = probe_model_connection(
        auth_settings,
        client=mock_client(status_code=401),
    )
    assert auth_result["ok"] is False
    assert auth_result["error_code"] == "provider_auth_failed"
