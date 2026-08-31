import hashlib
import json
from dataclasses import replace

import pytest

from app.providers import RubricAssessmentResult
from app.question_bank import build_question_specs
from app.rubrics import build_rubric
from app.assessment_engine import (
    AssessmentResponseError,
    aggregate_assessment,
    build_explicit_unknown_assessment,
    mark_invalid_observations,
    parse_model_assessment,
    validate_rubric_observations,
)


QUESTION = build_question_specs()[0]
RUBRIC = build_rubric(QUESTION)
ANSWER = "核心正确；机制说明；场景分析；工程取舍"


def model_content(overrides=None):
    overrides = overrides or {}
    markers = {
        "correctness": "核心正确",
        "mechanism": "机制说明",
        "scenario": "场景分析",
        "engineering": "工程取舍",
    }
    items = []
    for item in RUBRIC.items:
        marker = markers[item.rubric_id]
        start = ANSWER.index(marker)
        payload = {
            "rubric_id": item.rubric_id,
            "level": 3,
            "evidence_start": start,
            "evidence_end": start + len(marker),
            "quoted_text": marker,
            "confidence": 0.8,
        }
        payload.update(overrides.get(item.rubric_id, {}))
        items.append(payload)
    return json.dumps({"items": items}, ensure_ascii=False)


def valid_item(rubric_id: str, level: int, confidence: float = 0.8):
    marker = {
        "correctness": "核心正确",
        "mechanism": "机制说明",
        "scenario": "场景分析",
        "engineering": "工程取舍",
    }[rubric_id]
    start = ANSWER.index(marker)
    return RubricAssessmentResult(
        rubric_id=rubric_id,
        level=level,
        evidence_start=start,
        evidence_end=start + len(marker),
        quoted_text=marker,
        answer_text_hash=hashlib.sha256(ANSWER.encode("utf-8")).hexdigest(),
        confidence=confidence,
    )


def test_parse_model_assessment_requires_each_rubric_once():
    content = json.dumps(
        {
            "items": [
                {
                    "rubric_id": "correctness",
                    "level": 3,
                    "evidence_start": 0,
                    "evidence_end": 4,
                    "quoted_text": "核心正确",
                    "confidence": 0.8,
                }
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(AssessmentResponseError, match="Rubric"):
        parse_model_assessment(content, RUBRIC, ANSWER)


def test_parse_model_assessment_rejects_evidence_mismatch():
    content = model_content({"mechanism": {"quoted_text": "模型编造的证据"}})

    with pytest.raises(AssessmentResponseError, match="evidence|quoted_text"):
        parse_model_assessment(content, RUBRIC, ANSWER)


def test_aggregate_uses_half_up_rounding_and_program_generated_gaps():
    items = [
        valid_item("correctness", 3),
        valid_item("mechanism", 2),
        valid_item("scenario", 3),
        valid_item("engineering", 4),
    ]

    result = aggregate_assessment(QUESTION, ANSWER, items, "siliconflow-blind-rubric-v1")

    assert result.level == 3
    assert result.gaps == ("mechanism",)
    assert result.confidence == 0.8


def test_parser_rejects_duplicate_extra_and_out_of_range_items():
    duplicate = json.loads(model_content())
    duplicate["items"].append(duplicate["items"][0])
    with pytest.raises(AssessmentResponseError, match="Rubric"):
        parse_model_assessment(json.dumps(duplicate), RUBRIC, ANSWER)

    extra = json.loads(model_content())
    extra["items"][0]["rubric_id"] = "not-in-rubric"
    with pytest.raises(AssessmentResponseError, match="Rubric"):
        parse_model_assessment(json.dumps(extra), RUBRIC, ANSWER)

    invalid_level = json.loads(model_content())
    invalid_level["items"][0]["level"] = 5
    with pytest.raises(AssessmentResponseError, match="level"):
        parse_model_assessment(json.dumps(invalid_level), RUBRIC, ANSWER)

    invalid_confidence = json.loads(model_content())
    invalid_confidence["items"][0]["confidence"] = 1.1
    with pytest.raises(AssessmentResponseError, match="confidence"):
        parse_model_assessment(json.dumps(invalid_confidence), RUBRIC, ANSWER)


def test_evidence_validation_checks_offsets_and_answer_hash():
    item = valid_item("correctness", 3)
    validate_rubric_observations((item,), RUBRIC, ANSWER)

    bad_range = replace(item, evidence_end=item.evidence_start - 1)
    with pytest.raises(AssessmentResponseError, match="range"):
        validate_rubric_observations((bad_range,), RUBRIC, ANSWER)

    bad_hash = replace(item, answer_text_hash="0" * 64)
    with pytest.raises(AssessmentResponseError, match="hash"):
        validate_rubric_observations((bad_hash,), RUBRIC, ANSWER)


def test_invalid_observations_are_retained_with_reason():
    invalid = mark_invalid_observations((valid_item("correctness", 3),), "证据无法定位")

    assert invalid[0].validity == "invalid"
    assert invalid[0].invalid_reason == "证据无法定位"


def test_explicit_unknown_creates_valid_zero_level_rubric_observations():
    result = build_explicit_unknown_assessment(QUESTION, "不知道")

    assert result.level == 0
    assert result.gaps == tuple(item.rubric_id for item in RUBRIC.items)
    assert len(result.rubric_items) == 4
    assert all(item.level == 0 for item in result.rubric_items)
    assert all(item.validity == "valid" for item in result.rubric_items)
