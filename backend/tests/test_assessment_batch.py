import json

import httpx
import pytest
from sqlalchemy import inspect

import app.assessment_engine as assessment_engine
import app.providers as providers
import app.schemas as schemas
from app.question_bank import build_question_specs
from app.rubrics import build_rubric
from app.database import create_database
from app.models import AssessmentRun


def make_cases():
    case_type = getattr(providers, "BatchAssessmentCase", None)
    assert case_type is not None, "BatchAssessmentCase is not implemented"
    questions = build_question_specs()[:2]
    return tuple(
        case_type(
            answer_id=f"answer-{index}",
            question_id=f"question-{index}",
            question=question,
            answer_text=f"回答 {index}：我说明了机制、边界和工程取舍。",
        )
        for index, question in enumerate(questions, start=1)
    )


def valid_case_payload(case):
    return {
        "answer_id": case.answer_id,
        "question_id": case.question_id,
        "rubric_items": [
            {
                "rubric_id": item.rubric_id,
                "level": 3,
                "evidence_start": 0,
                "evidence_end": len(case.answer_text),
                "quoted_text": case.answer_text,
                "confidence": 0.8,
            }
            for item in build_rubric(case.question).items
        ],
    }


def batch_model_response(cases):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"items": [valid_case_payload(case) for case in cases]},
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def make_provider(cases, captured):
    request_count = {"value": 0}

    def handler(request):
        request_count["value"] += 1
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=batch_model_response(cases))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = providers.SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=client,
    )
    return provider, request_count


def test_batch_prompt_contains_independent_cases_without_resume_context():
    cases = make_cases()
    prompt_builder = getattr(providers, "build_batch_assessment_prompt", None)
    assert callable(prompt_builder), "build_batch_assessment_prompt is not implemented"

    system_prompt, user_prompt = prompt_builder(cases)

    assert "独立" in system_prompt + user_prompt
    assert all(case.question.prompt in user_prompt for case in cases)
    assert all(case.answer_text in user_prompt for case in cases)
    assert "resume_text" not in user_prompt
    assert "过去分数" not in user_prompt


def test_batch_parser_requires_exact_case_and_rubric_sets():
    cases = make_cases()
    parser = getattr(assessment_engine, "parse_batch_model_assessment", None)
    assert callable(parser), "parse_batch_model_assessment is not implemented"

    content = json.dumps({"items": [valid_case_payload(case) for case in cases]})
    results = parser(content, cases)

    assert {item.answer_id for item in results} == {case.answer_id for case in cases}
    assert all(len(item.result.rubric_items) == 4 for item in results)


def test_batch_parser_rejects_missing_case():
    cases = make_cases()
    parser = getattr(assessment_engine, "parse_batch_model_assessment", None)
    assert callable(parser), "parse_batch_model_assessment is not implemented"
    content = json.dumps({"items": [valid_case_payload(cases[0])]})

    with pytest.raises(assessment_engine.AssessmentResponseError):
        parser(content, cases)


def test_siliconflow_batch_provider_uses_one_http_request():
    cases = make_cases()
    captured = {}
    provider, request_count = make_provider(cases, captured)

    result = provider.assess_batch(cases)

    assert len(result) == 2
    assert request_count["value"] == 1
    request_text = json.dumps(captured["json"], ensure_ascii=False)
    assert "resume_text" not in request_text
    assert "历史画像" not in request_text
    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_batch_persistence_and_response_contract(tmp_path):
    engine, _ = create_database(f"sqlite:///{tmp_path / 'batch.db'}")

    assert hasattr(AssessmentRun, "batch_id")
    columns = {column["name"] for column in inspect(engine).get_columns("assessment_runs")}
    assert "batch_id" in columns

    response_type = getattr(schemas, "AssessmentBatchResponse", None)
    assert response_type is not None, "AssessmentBatchResponse is not implemented"
    response = response_type(
        status="valid",
        batch_id="batch-1",
        evaluated_count=2,
        total_count=3,
        assessments=[],
    )
    assert response.batch_id == "batch-1"
    assert response.evaluated_count == 2
