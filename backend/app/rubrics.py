from dataclasses import dataclass

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
    return RubricSnapshot(
        version=question.rubric_version,
        items=(
            RubricItem("correctness", "核心概念、方案或判断是否正确"),
            RubricItem("mechanism", "是否解释机制、原因或工作原理"),
            RubricItem("scenario", "是否结合当前问题进行场景化分析"),
            RubricItem("engineering", "是否说明边界、取舍、故障或可执行方案"),
        ),
    )
