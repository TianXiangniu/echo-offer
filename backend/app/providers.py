from dataclasses import dataclass
import hashlib
from typing import Protocol

from .question_bank import QuestionSpec


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    level: int
    evidence_start: int
    evidence_end: int
    quoted_text: str
    answer_text_hash: str
    gaps: tuple[str, ...]
    confidence: float


class AssessmentProvider(Protocol):
    def assess(
        self, question: QuestionSpec, answer_text: str, status: str
    ) -> AssessmentResult:
        ...


class RuleBasedAssessmentProvider:
    """Deterministic local evaluator used until a model Provider is added."""

    _KNOWN_STATUSES = {"submitted", "explicit_unknown"}
    _DEPTH_TERMS = ("机制", "边界", "取舍", "权衡", "监控", "失败", "降级", "trade-off")

    def assess(
        self, question: QuestionSpec, answer_text: str, status: str
    ) -> AssessmentResult:
        if status not in self._KNOWN_STATUSES:
            raise ValueError("status must be submitted or explicit_unknown")

        if status == "submitted" and not answer_text.strip():
            raise ValueError("answer_text cannot be blank for submitted status")

        answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
        if status == "explicit_unknown":
            return AssessmentResult(
                level=0,
                evidence_start=0,
                evidence_end=len(answer_text),
                quoted_text=answer_text,
                answer_text_hash=answer_hash,
                gaps=question.signals,
                confidence=0.9,
            )

        matched_signals = tuple(
            signal for signal in question.signals if signal.lower() in answer_text.lower()
        )
        level = 0
        if len(answer_text.strip()) >= 15:
            level += 1
        if matched_signals:
            level += 1
        if len(matched_signals) >= 2:
            level += 1
        if len(matched_signals) >= 3 or any(
            term in answer_text.lower() for term in self._DEPTH_TERMS
        ):
            level += 1
        level = min(4, level)

        confidence = min(
            0.95,
            round(0.45 + (0.08 * len(matched_signals)) + (0.02 if len(answer_text) >= 60 else 0), 2),
        )
        gaps = tuple(signal for signal in question.signals if signal not in matched_signals)
        return AssessmentResult(
            level=level,
            evidence_start=0,
            evidence_end=len(answer_text),
            quoted_text=answer_text,
            answer_text_hash=answer_hash,
            gaps=gaps,
            confidence=confidence,
        )
