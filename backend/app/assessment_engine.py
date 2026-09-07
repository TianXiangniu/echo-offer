import hashlib
import json
import math
from collections.abc import Sequence
from typing import Any

from .model_output import ModelOutputError, parse_model_json
from .providers import (
    AssessmentResponseError,
    AssessmentResult,
    BatchAssessmentCase,
    BatchAssessmentItem,
    RubricAssessmentResult,
)
from .question_bank import QuestionSpec
from .rubrics import RubricSnapshot, build_rubric

# 模型引用时常改变引号形态；全角弯引号与半角引号等长，可无损替换
_QUOTE_TRANSLATION = str.maketrans(
    {"“": '"', "”": '"', "„": '"', "‟": '"', "‘": "'", "’": "'", "‚": "'", "‛": "'"}
)


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """引号统一 + 空白压缩。返回（归一化文本, 归一化位置 → 原文位置）。"""
    unified = text.translate(_QUOTE_TRANSLATION)
    out: list[str] = []
    mapping: list[int] = []
    previous_space = True
    for index, char in enumerate(unified):
        if char.isspace():
            if previous_space:
                continue
            out.append(" ")
            mapping.append(index)
            previous_space = True
        else:
            out.append(char)
            mapping.append(index)
            previous_space = False
    return "".join(out), mapping


def _locate_quote(haystack: str, quote: str) -> tuple[int, int] | None:
    """在 haystack 中定位 quote，返回原文区间。

    逐字精确优先；失败后用归一化匹配（覆盖模型改写空白/引号的常见情况），
    命中区间映射回原文，证据审计语义不变。
    """
    if not quote:
        return None
    direct = haystack.find(quote)
    if direct >= 0:
        return direct, direct + len(quote)
    normalized_haystack, mapping = _normalize_with_map(haystack)
    normalized_quote, _ = _normalize_with_map(quote)
    normalized_quote = normalized_quote.strip()
    if not normalized_quote:
        return None
    position = normalized_haystack.find(normalized_quote)
    if position < 0:
        return None
    start = mapping[position]
    last = mapping[min(position + len(normalized_quote) - 1, len(mapping) - 1)]
    return start, last + 1


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


def _evidence_sources(answer_text: str, followup_text: str = "") -> dict[str, str]:
    """hash -> 原文。追问回答与首答共同构成评分证据的合法来源。"""
    sources = {hashlib.sha256(answer_text.encode("utf-8")).hexdigest(): answer_text}
    if followup_text:
        sources[hashlib.sha256(followup_text.encode("utf-8")).hexdigest()] = followup_text
    return sources


def validate_rubric_observations(
    items: Sequence[RubricAssessmentResult],
    rubric: RubricSnapshot,
    answer_text: str,
    followup_text: str = "",
) -> None:
    known_ids = {item.rubric_id for item in rubric.items}
    seen_ids: set[str] = set()
    sources = _evidence_sources(answer_text, followup_text)

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
        if item.validity == "invalid":
            continue
        source_text = sources.get(item.answer_text_hash)
        if source_text is None:
            raise AssessmentResponseError("answer_hash_mismatch", "answer hash does not match")
        raw_slice = source_text[item.evidence_start : item.evidence_end]
        if raw_slice != item.quoted_text:
            # 宽容定位后切片与模型引文允许空白/引号形态差异，语义内容必须一致
            normalized_slice, _ = _normalize_with_map(raw_slice)
            normalized_quote, _ = _normalize_with_map(item.quoted_text)
            if normalized_slice != normalized_quote.strip():
                raise AssessmentResponseError(
                    "invalid_evidence", "quoted_text does not match answer slice"
                )


def parse_model_assessment(
    content: object,
    rubric: RubricSnapshot,
    answer_text: str,
    followup_text: str = "",
) -> tuple[RubricAssessmentResult, ...]:
    try:
        payload = parse_model_json(content)
    except ModelOutputError as exc:
        raise AssessmentResponseError(exc.code, str(exc)) from exc

    payload = _require_dict(payload, "模型返回必须是 JSON 对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AssessmentResponseError("invalid_model_response", "模型返回缺少 items 数组")

    answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    followup_hash = (
        hashlib.sha256(followup_text.encode("utf-8")).hexdigest() if followup_text else None
    )
    items: list[RubricAssessmentResult] = []
    for raw_item in raw_items:
        item = _require_dict(raw_item, "Rubric 项必须是对象")
        rubric_id = item.get("rubric_id")
        if not isinstance(rubric_id, str) or not rubric_id:
            raise AssessmentResponseError("invalid_rubric", "Rubric ID 无效")
        level = _require_int(item.get("level"), "invalid_level", "Rubric level 必须是整数")
        # 模型偶发漏掉 quoted_text：宽容为无证据观察（invalid），不整批拒绝
        quoted_text = item.get("quoted_text")
        if quoted_text is not None and not isinstance(quoted_text, str):
            raise AssessmentResponseError("invalid_evidence", "quoted_text 必须是字符串")
        confidence = _require_float(
            item.get("confidence"),
            "invalid_confidence",
            "confidence 必须是数字",
        )
        located = None
        source_hash = answer_hash
        if quoted_text:
            located = _locate_quote(answer_text, quoted_text)
            if located is None and followup_text:
                located = _locate_quote(followup_text, quoted_text)
                if located is not None:
                    source_hash = followup_hash
        evidence_start, evidence_end = located if located is not None else (0, 0)
        validity = "valid" if not quoted_text or located is not None else "invalid"
        invalid_reason = None if validity == "valid" else "quoted_text 不在回答原文中"
        items.append(
            RubricAssessmentResult(
                rubric_id=rubric_id,
                level=level,
                evidence_start=evidence_start,
                evidence_end=evidence_end,
                quoted_text=quoted_text,
                answer_text_hash=source_hash,
                confidence=confidence,
                validity=validity,
                invalid_reason=invalid_reason,
            )
        )

    expected_ids = {item.rubric_id for item in rubric.items}
    actual_ids = {item.rubric_id for item in items}
    if len(items) != len(actual_ids) or actual_ids != expected_ids:
        raise AssessmentResponseError("invalid_rubric", "模型必须完整且唯一地返回冻结 Rubric")

    validate_rubric_observations(items, rubric, answer_text, followup_text)
    return tuple(items)


def parse_batch_model_assessment(
    content: object,
    cases: Sequence[BatchAssessmentCase],
    evaluator: str = "siliconflow-blind-rubric-v1",
) -> tuple[BatchAssessmentItem, ...]:
    try:
        payload = parse_model_json(content)
    except ModelOutputError as exc:
        raise AssessmentResponseError(exc.code, str(exc)) from exc

    payload = _require_dict(payload, "模型返回必须是 JSON 对象")
    if set(payload) != {"items"}:
        raise AssessmentResponseError("invalid_model_response", "批量模型返回包含未允许的字段")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AssessmentResponseError("invalid_model_response", "批量模型返回缺少 items 数组")

    # 关联优先用短序号 case_id（模型抄写友好）；兼容旧的 answer_id+question_id 长键
    case_by_ref = {case.case_ref: case for case in cases if case.case_ref}
    case_by_key = {(case.answer_id, case.question_id): case for case in cases}
    if not case_by_ref and len(case_by_key) != len(cases):
        raise AssessmentResponseError("invalid_batch_case", "批量评分 case ID 必须唯一")
    expected_refs = set(case_by_ref)

    seen_cases: set[int] = set()
    results: list[BatchAssessmentItem] = []
    for raw_item in raw_items:
        item = _require_dict(raw_item, "批量评分项必须是对象")
        if set(item) - {"case_id", "answer_id", "question_id", "rubric_items", "comment"}:
            raise AssessmentResponseError("invalid_model_response", "批量评分项包含未允许的字段")
        case = None
        if "case_id" in item:
            case_ref = item.get("case_id")
            if not isinstance(case_ref, str):
                raise AssessmentResponseError("invalid_batch_case", "批量评分项缺少有效 case ID")
            case = case_by_ref.get(case_ref)
        elif {"answer_id", "question_id"}.issubset(item):
            key = (item.get("answer_id"), item.get("question_id"))
            case = case_by_key.get(key) if all(isinstance(k, str) for k in key) else None
        if case is None or id(case) in seen_cases:
            raise AssessmentResponseError("invalid_batch_case", "批量评分 case ID 不完整或重复")
        seen_cases.add(id(case))
        expected_refs.discard(case.case_ref)
        commentary = item.get("comment", "")
        commentary = " ".join(str(commentary).split())[:80] if isinstance(commentary, str) else ""
        raw_rubric_items = item.get("rubric_items")
        if not isinstance(raw_rubric_items, list):
            raise AssessmentResponseError("invalid_rubric", "批量评分项缺少 rubric_items 数组")
        for raw_rubric_item in raw_rubric_items:
            if not isinstance(raw_rubric_item, dict):
                raise AssessmentResponseError("invalid_rubric", "Rubric 项必须是对象")
            required_fields = {"rubric_id", "level", "quoted_text", "confidence"}
            if not required_fields.issubset(raw_rubric_item):
                raise AssessmentResponseError("invalid_model_response", "Rubric 项缺少必需字段")
            # 未知字段忽略：模型偶尔多带字段，程序只读取已知字段
        rubric_content = json.dumps({"items": raw_rubric_items}, ensure_ascii=False)
        rubric_items = parse_model_assessment(
            rubric_content,
            build_rubric(case.question),
            case.answer_text,
            case.followup_text,
        )
        result = aggregate_assessment(
            case.question,
            case.answer_text,
            rubric_items,
            evaluator,
            followup_text=case.followup_text,
        )
        results.append(
            BatchAssessmentItem(
                answer_id=case.answer_id,
                question_id=case.question_id,
                result=result,
                commentary=commentary,
            )
        )

    if len(seen_cases) != len(cases):
        raise AssessmentResponseError("invalid_batch_case", "批量模型必须完整返回每个 case")
    return tuple(results)


def aggregate_assessment(
    question: QuestionSpec,
    answer_text: str,
    items: Sequence[RubricAssessmentResult],
    evaluator: str,
    followup_text: str = "",
) -> AssessmentResult:
    rubric = build_rubric(question)
    expected_ids = {item.rubric_id for item in rubric.items}
    actual_ids = {item.rubric_id for item in items}
    if len(items) != len(actual_ids) or actual_ids != expected_ids:
        raise AssessmentResponseError("invalid_rubric", "不能聚合不完整的 Rubric 结果")
    validate_rubric_observations(items, rubric, answer_text, followup_text)

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
