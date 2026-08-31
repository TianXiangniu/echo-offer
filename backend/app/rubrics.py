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


def build_rubric(question: QuestionSpec) -> RubricSnapshot:
    snapshot = getattr(question, "rubric_snapshot", None)
    if isinstance(snapshot, RubricSnapshot):
        return snapshot
    return RubricSnapshot(
        version=question.rubric_version,
        items=(
            RubricItem("correctness", "核心概念、方案或判断是否正确"),
            RubricItem("mechanism", "是否解释机制、原因或工作原理"),
            RubricItem("scenario", "是否结合当前问题进行场景化分析"),
            RubricItem("engineering", "是否说明边界、取舍、故障或可执行方案"),
        ),
    )


def rubric_to_dict(rubric: RubricSnapshot) -> dict[str, Any]:
    return {
        "version": rubric.version,
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
    return RubricSnapshot(version=payload["version"], items=items)
