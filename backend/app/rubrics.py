from dataclasses import dataclass
from typing import Any

from .question_bank import QuestionSpec


@dataclass(frozen=True, slots=True)
class RubricItem:
    rubric_id: str
    criterion: str
    reference_facts: tuple[str, ...] = ()
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class RubricSnapshot:
    version: str
    items: tuple[RubricItem, ...]
    reference_facts: tuple[str, ...] = ()


DEFAULT_CRITERIA: tuple[tuple[str, str], ...] = (
    ("correctness", "核心概念、方案或判断是否正确；概念错误、因果颠倒或编造机制应给低分"),
    ("mechanism", "是否解释了机制或原理——说清为什么这样工作，而不是罗列名词"),
    ("scenario", "是否结合具体场景、数据或实例分析；有真实细节而非泛泛而谈"),
    ("engineering", "是否说明边界条件、代价取舍、失败处理或可落地的执行方案"),
)


def build_rubric(question: QuestionSpec) -> RubricSnapshot:
    if isinstance(question.rubric_snapshot, RubricSnapshot):
        return question.rubric_snapshot
    weights = dict(question.rubric_weights)
    overrides = dict(question.criteria_override)
    return RubricSnapshot(
        version=question.rubric_version,
        items=tuple(
            RubricItem(
                rubric_id,
                overrides.get(rubric_id, criterion),
                weight=weights.get(rubric_id, 1.0),
            )
            for rubric_id, criterion in DEFAULT_CRITERIA
        ),
        reference_facts=question.reference_facts,
    )


def rubric_to_dict(rubric: RubricSnapshot) -> dict[str, Any]:
    return {
        "version": rubric.version,
        "reference_facts": list(rubric.reference_facts),
        "items": [
            {
                "rubric_id": item.rubric_id,
                "criterion": item.criterion,
                "reference_facts": list(item.reference_facts),
                "weight": item.weight,
            }
            for item in rubric.items
        ],
    }


def rubric_from_dict(payload: dict[str, Any]) -> RubricSnapshot:
    raw_items = payload.get("items")
    if not isinstance(payload.get("version"), str) or not isinstance(raw_items, list):
        raise ValueError("invalid rubric snapshot")
    items = tuple(
        RubricItem(
            rubric_id=item["rubric_id"],
            criterion=item["criterion"],
            reference_facts=tuple(item.get("reference_facts", [])),
            weight=float(item.get("weight", 1.0)),
        )
        for item in raw_items
    )
    if not items or any(not item.rubric_id or not item.criterion for item in items):
        raise ValueError("invalid rubric items")
    return RubricSnapshot(
        version=payload["version"],
        items=items,
        reference_facts=tuple(payload.get("reference_facts", []) or []),
    )
