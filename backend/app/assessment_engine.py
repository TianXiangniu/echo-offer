import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from .providers import AssessmentResult, RubricAssessmentResult
from .question_bank import QuestionSpec
from .rubrics import RubricSnapshot, build_rubric


class AssessmentResponseError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require_dict(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssessmentResponseError("invalid_model_response", message)
    return value


def _require_int(value: Any, code: str, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssessmentResponseError(code, message)
    return value


def _require_float(value: Any, code: str, message: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssessmentResponseError(code, message)
    return float(value)


def validate_rubric_observations(
    items: Sequence[RubricAssessmentResult],
    rubric: RubricSnapshot,
    answer_text: str,
) -> None:
    known_ids = {item.rubric_id for item in rubric.items}
    seen_ids: set[str] = set()
    expected_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()

    for item in items:
        if item.rubric_id not in known_ids or item.rubric_id in seen_ids:
            raise AssessmentResponseError("invalid_rubric", "Rubric items must match the frozen rubric")
        seen_ids.add(item.rubric_id)
        if not 0 <= item.level <= 4:
            raise AssessmentResponseError("invalid_level", "Rubric level must be between 0 and 4")
        if not 0 <= item.confidence <= 1:
            raise AssessmentResponseError("invalid_confidence", "confidence must be between 0 and 1")
        if item.evidence_start < 0 or item.evidence_end < item.evidence_start:
            raise AssessmentResponseError("invalid_evidence_range", "evidence range is invalid")
        if answer_text[item.evidence_start : item.evidence_end] != item.quoted_text:
            raise AssessmentResponseError("invalid_evidence", "quoted_text does not match answer slice")
        if item.answer_text_hash != expected_hash:
            raise AssessmentResponseError("answer_hash_mismatch", "answer hash does not match")


def parse_model_assessment(
    content: str,
    rubric: RubricSnapshot,
    answer_text: str,
) -> tuple[RubricAssessmentResult, ...]:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssessmentResponseError("invalid_model_response", "模型返回不是合法 JSON") from exc

    payload = _require_dict(payload, "模型返回必须是 JSON 对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AssessmentResponseError("invalid_model_response", "模型返回缺少 items 数组")

    answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    items: list[RubricAssessmentResult] = []
    for raw_item in raw_items:
        item = _require_dict(raw_item, "Rubric 项必须是对象")
        rubric_id = item.get("rubric_id")
        if not isinstance(rubric_id, str) or not rubric_id:
            raise AssessmentResponseError("invalid_rubric", "Rubric ID 无效")
        level = _require_int(item.get("level"), "invalid_level", "Rubric level 必须是整数")
        evidence_start = _require_int(
            item.get("evidence_start"),
            "invalid_evidence_range",
            "evidence_start 必须是整数",
        )
        evidence_end = _require_int(
            item.get("evidence_end"),
            "invalid_evidence_range",
            "evidence_end 必须是整数",
        )
        quoted_text = item.get("quoted_text")
        if not isinstance(quoted_text, str):
            raise AssessmentResponseError("invalid_evidence", "quoted_text 必须是字符串")
        confidence = _require_float(
            item.get("confidence"),
            "invalid_confidence",
            "confidence 必须是数字",
        )
        items.append(
            RubricAssessmentResult(
                rubric_id=rubric_id,
                level=level,
                evidence_start=evidence_start,
                evidence_end=evidence_end,
                quoted_text=quoted_text,
                answer_text_hash=answer_hash,
                confidence=confidence,
            )
        )

    expected_ids = {item.rubric_id for item in rubric.items}
    actual_ids = {item.rubric_id for item in items}
    if len(items) != len(actual_ids) or actual_ids != expected_ids:
        raise AssessmentResponseError("invalid_rubric", "模型必须完整且唯一地返回冻结 Rubric")

    validate_rubric_observations(items, rubric, answer_text)
    return tuple(items)


def aggregate_assessment(
    question: QuestionSpec,
    answer_text: str,
    items: Sequence[RubricAssessmentResult],
    evaluator: str,
) -> AssessmentResult:
    rubric = build_rubric(question)
    expected_ids = {item.rubric_id for item in rubric.items}
    actual_ids = {item.rubric_id for item in items}
    if len(items) != len(actual_ids) or actual_ids != expected_ids:
        raise AssessmentResponseError("invalid_rubric", "不能聚合不完整的 Rubric 结果")
    validate_rubric_observations(items, rubric, answer_text)

    weights = {item.rubric_id: item.weight for item in rubric.items}
    total_weight = sum(weights.values())
    average_level = sum(item.level * weights[item.rubric_id] for item in items) / total_weight
    average_confidence = sum(
        item.confidence * weights[item.rubric_id] for item in items
    ) / total_weight
    level = min(4, max(0, math.floor(average_level + 0.5)))
    answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    return AssessmentResult(
        level=level,
        evidence_start=0,
        evidence_end=len(answer_text),
        quoted_text=answer_text,
        answer_text_hash=answer_hash,
        gaps=tuple(item.rubric_id for item in items if item.level < 3),
        confidence=round(average_confidence, 2),
        rubric_items=tuple(items),
        evaluator=evaluator,
    )


def build_explicit_unknown_assessment(
    question: QuestionSpec,
    answer_text: str,
    evaluator: str = "siliconflow-blind-rubric-v1",
) -> AssessmentResult:
    answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    evidence_end = len(answer_text)
    items = tuple(
        RubricAssessmentResult(
            rubric_id=rubric_item.rubric_id,
            level=0,
            evidence_start=0,
            evidence_end=evidence_end,
            quoted_text=answer_text,
            answer_text_hash=answer_hash,
            confidence=0.9,
        )
        for rubric_item in build_rubric(question).items
    )
    return aggregate_assessment(question, answer_text, items, evaluator)


def mark_invalid_observations(
    items: Sequence[RubricAssessmentResult],
    reason: str,
) -> tuple[RubricAssessmentResult, ...]:
    return tuple(replace(item, validity="invalid", invalid_reason=reason) for item in items)
