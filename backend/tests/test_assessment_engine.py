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


def compact_model_content(quoted_text=ANSWER):
    items = [
        {
            "rubric_id": item.rubric_id,
            "level": level,
            "quoted_text": quoted_text,
            "confidence": 0.8,
        }
        for item, level in zip(RUBRIC.items, (3, 2, 3, 4), strict=True)
    ]
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


def test_parse_model_assessment_derives_evidence_offsets_and_hash():
    result = parse_model_assessment(compact_model_content(), RUBRIC, ANSWER)

    assert result[0].evidence_start == 0
    assert result[0].evidence_end == len(ANSWER)
    assert result[0].quoted_text == ANSWER
    assert result[0].answer_text_hash == hashlib.sha256(ANSWER.encode()).hexdigest()


def test_parse_model_assessment_keeps_unmatched_evidence_invalid():
    result = parse_model_assessment(compact_model_content("回答中没有这句话"), RUBRIC, ANSWER)

    assert result[0].validity == "invalid"
    assert result[0].invalid_reason


def test_parse_model_assessment_marks_evidence_mismatch_invalid():
    content = model_content({"mechanism": {"quoted_text": "模型编造的证据"}})

    result = parse_model_assessment(content, RUBRIC, ANSWER)

    mechanism = next(item for item in result if item.rubric_id == "mechanism")
    assert mechanism.validity == "invalid"


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


def test_explicit_unknown_creates_valid_zero_level_rubric_observations():
    result = build_explicit_unknown_assessment(QUESTION, "不知道")

    assert result.level == 0
    assert result.gaps == tuple(item.rubric_id for item in RUBRIC.items)
    assert len(result.rubric_items) == 4
    assert all(item.level == 0 for item in result.rubric_items)
    assert all(item.validity == "valid" for item in result.rubric_items)


def test_parse_batch_accepts_optional_comment_and_caps_length():
    from app.assessment_engine import BatchAssessmentCase, parse_batch_model_assessment

    specs = build_question_specs()
    case = BatchAssessmentCase(
        answer_id="a1",
        question_id="q1",
        question=specs[3],
        answer_text="回答内容足够长，讲了机制也讲了边界。" * 3,
    )
    rubric_ids = ["correctness", "mechanism", "scenario", "engineering"]
    payload = {
        "items": [
            {
                "answer_id": "a1",
                "question_id": "q1",
                "comment": "很长的评论" * 40,
                "rubric_items": [
                    {
                        "rubric_id": rubric_id,
                        "level": 3,
                        "quoted_text": "回答内容足够长，讲了机制",
                        "confidence": 0.8,
                    }
                    for rubric_id in rubric_ids
                ],
            }
        ]
    }

    items = parse_batch_model_assessment(json.dumps(payload, ensure_ascii=False), [case])

    assert items[0].commentary.startswith("很长的评论")
    assert len(items[0].commentary) <= 80


def test_locate_quote_tolerates_whitespace_and_quote_variants():
    from app.assessment_engine import _locate_quote

    haystack = "方案是：查询改写  加  混合检索，\n  命中率提升 18%。"
    # 多空白差异
    assert _locate_quote(haystack, "查询改写 加 混合检索") is not None
    # 换行差异
    assert _locate_quote(haystack, "混合检索， 命中率提升") is not None
    # 引号形态差异（模型把弯引号转成直引号）
    curly = "他说" + "\u201c" + "混合检索" + "\u201d" + "很好。"
    assert _locate_quote('他说"混合检索"很好。', curly) is not None
    # 编造内容仍然找不到
    assert _locate_quote(haystack, "完全不存在的内容") is None
    # 命中区间映射回原文：切片归一化后与引文一致
    located = _locate_quote(haystack, "查询改写 加 混合检索")
    start, end = located
    from app.assessment_engine import _normalize_with_map

    normalized_slice, _ = _normalize_with_map(haystack[start:end])
    normalized_quote, _ = _normalize_with_map("查询改写 加 混合检索")
    assert normalized_slice == normalized_quote


def test_parse_model_assessment_tolerates_whitespace_quoted_text():
    from app.assessment_engine import parse_model_assessment

    specs = build_question_specs()
    rubric = build_rubric(specs[3])
    answer_text = "先讲机制：BM25 负责精确匹配，\n向量负责语义泛化。边界：术语库要持续维护。"
    content = json.dumps(
        {
            "items": [
                {
                    "rubric_id": "correctness",
                    "level": 3,
                    # 模型把换行改成了空格
                    "quoted_text": "BM25 负责精确匹配， 向量负责语义泛化。",
                    "confidence": 0.8,
                },
                {
                    "rubric_id": "mechanism",
                    "level": 3,
                    "quoted_text": "术语库要持续维护。",
                    "confidence": 0.8,
                },
                {
                    "rubric_id": "scenario",
                    "level": 3,
                    "quoted_text": "先讲机制",
                    "confidence": 0.8,
                },
                {
                    "rubric_id": "engineering",
                    "level": 3,
                    "quoted_text": "边界：术语库要持续维护。",
                    "confidence": 0.8,
                },
            ]
        },
        ensure_ascii=False,
    )

    items = parse_model_assessment(content, rubric, answer_text)

    assert all(item.validity == "valid" for item in items)
