import json

import httpx
import pytest

from app.providers import (
    AssessmentProviderError,
    SiliconFlowAssessmentProvider,
)
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
    assert error.value.code == "invalid_model_response"
