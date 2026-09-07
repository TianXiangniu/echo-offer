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


def test_batch_provider_accepts_compact_rubric_items_without_model_offsets():
    cases = make_cases()

    def compact_response(request):
        compact_items = []
        for case in cases:
            compact_items.append(
                {
                    "answer_id": case.answer_id,
                    "question_id": case.question_id,
                    "rubric_items": [
                        {
                            "rubric_id": item.rubric_id,
                            "level": 3,
                            "quoted_text": case.answer_text,
                            "confidence": 0.8,
                        }
                        for item in build_rubric(case.question).items
                    ],
                }
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"items": compact_items})
                        }
                    }
                ]
            },
        )

    provider = providers.SiliconFlowAssessmentProvider(
        api_key="test-key",
        model="test-model",
        base_url="https://example.test/v1",
        timeout_seconds=2,
        client=httpx.Client(transport=httpx.MockTransport(compact_response)),
    )

    result = provider.assess_batch(cases)

    assert len(result) == len(cases)
    assert result[0].result.rubric_items[0].evidence_start == 0


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


def _make_verifying_client(tmp_path, verdicts):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import FakeVerifyingProvider

    def _run_full_interview(client):
        from tests.conftest import create_test_session

        session_id, questions = create_test_session(client)
        for index, question in enumerate(questions, start=1):
            client.post(
                f"/api/sessions/{session_id}/answers",
                json={
                    "question_id": question["id"],
                    "client_submission_id": f"v-{index}",
                    "status": "submitted",
                    "answer_text": f"第 {index} 题回答：机制、边界、取舍齐全。",
                },
            )
        response = client.post(f"/api/sessions/{session_id}/assessment")
        assert response.status_code == 200
        return session_id, response

    app = create_app(
        f"sqlite:///{tmp_path / 'verify.db'}",
        upload_root=tmp_path / "uploads",
        assessment_provider=FakeVerifyingProvider(verdicts=verdicts),
    )
    with TestClient(app) as client:
        yield client, _run_full_interview


def test_verifier_irrelevant_quote_downgrades_run(tmp_path):
    for client, run_interview in _make_verifying_client(
        tmp_path,
        verdicts={
            "correctness": {
                "quote_relevant": False,
                "level_supported": True,
                "suggested_level": None,
            }
        },
    ):
        _, response = run_interview(client)
        body = response.json()
        assert body["job_status"] in {"partial", "failed", "disputed"}
        assert body["job_error_code"] == "invalid_evidence"


def test_verifier_level_dispute_triggers_single_rerun(tmp_path):
    for client, run_interview in _make_verifying_client(
        tmp_path,
        verdicts={
            "mechanism": {
                "quote_relevant": True,
                "level_supported": False,
                "suggested_level": 0,
            }
        },
    ):
        _, response = run_interview(client)
        with client.app.state.session_factory() as db:
            from sqlalchemy import select

            from app.models import AssessmentRun

            runs = list(db.scalars(select(AssessmentRun)))
            reruns = [run for run in runs if run.attempt_number > 1]
            assert reruns
            # 每 case 只重评一次：重评结果不再次进入复核，不产生级联重评
            assert all(run.attempt_number == 2 for run in reruns)
        provider = client.app.state.assessment_provider
        assert provider.verify_calls >= 1


def _short_id_payload(cases, comment="评语"):
    from app.assessment_engine import json as _json  # noqa: F401

    items = []
    for index, case in enumerate(cases, start=1):
        items.append(
            {
                "case_id": f"c{index}",
                "comment": comment,
                "rubric_items": [
                    {
                        "rubric_id": rubric_id,
                        "level": 3,
                        "quoted_text": case.answer_text[:6],
                        "confidence": 0.8,
                    }
                    for rubric_id in ("correctness", "mechanism", "scenario", "engineering")
                ],
            }
        )
    return {"items": items}


def test_parse_batch_accepts_short_case_ids():
    import json as json_module

    from app.assessment_engine import (
        BatchAssessmentCase,
        parse_batch_model_assessment,
    )
    from app.question_bank import build_question_specs

    specs = build_question_specs()
    cases = [
        BatchAssessmentCase(
            answer_id=f"answer-{i}",
            question_id=f"question-{i}",
            question=specs[3],
            answer_text=f"这是第 {i} 个回答，机制清楚边界完整。",
            case_ref=f"c{i}",
        )
        for i in (1, 2)
    ]
    payload = _short_id_payload(cases)

    items = parse_batch_model_assessment(
        json_module.dumps(payload, ensure_ascii=False), cases
    )

    assert [item.answer_id for item in items] == ["answer-1", "answer-2"]
    assert all(item.commentary == "评语" for item in items)


def test_parse_batch_rejects_wrong_or_missing_case_ids():
    import json as json_module
    import pytest

    from app.assessment_engine import (
        AssessmentResponseError,
        BatchAssessmentCase,
        parse_batch_model_assessment,
    )
    from app.question_bank import build_question_specs

    specs = build_question_specs()
    cases = [
        BatchAssessmentCase(
            answer_id="answer-1",
            question_id="question-1",
            question=specs[3],
            answer_text="第一个回答内容。",
            case_ref="c1",
        ),
        BatchAssessmentCase(
            answer_id="answer-2",
            question_id="question-2",
            question=specs[3],
            answer_text="第二个回答内容。",
            case_ref="c2",
        ),
    ]
    # 模型抄错 case_id
    payload = _short_id_payload(cases)
    payload["items"][0]["case_id"] = "cx"
    with pytest.raises(AssessmentResponseError, match="不完整或重复"):
        parse_batch_model_assessment(json_module.dumps(payload, ensure_ascii=False), cases)
    # 模型漏掉一个 case
    payload2 = _short_id_payload(cases)
    payload2["items"] = payload2["items"][:1]
    with pytest.raises(AssessmentResponseError, match="必须完整返回"):
        parse_batch_model_assessment(json_module.dumps(payload2, ensure_ascii=False), cases)
