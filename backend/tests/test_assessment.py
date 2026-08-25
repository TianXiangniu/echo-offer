import hashlib

import pytest

from app.providers import RuleBasedAssessmentProvider
from app.question_bank import build_question_specs


def test_explicit_unknown_is_a_valid_zero_level_observation():
    answer = "不知道"

    result = RuleBasedAssessmentProvider().assess(
        build_question_specs()[0], answer, "explicit_unknown"
    )

    assert result.level == 0
    assert result.evidence_start == 0
    assert result.evidence_end == len(answer)
    assert result.quoted_text == answer
    assert result.answer_text_hash == hashlib.sha256(answer.encode("utf-8")).hexdigest()


def test_submitted_answer_evidence_matches_the_answer_hash():
    answer = "我们先做查询改写，再用混合检索召回候选文档，并通过 rerank 控制延迟和召回率。"

    result = RuleBasedAssessmentProvider().assess(
        build_question_specs()[4], answer, "submitted"
    )

    assert 1 <= result.level <= 4
    assert result.quoted_text == answer[result.evidence_start : result.evidence_end]
    assert result.answer_text_hash == hashlib.sha256(answer.encode("utf-8")).hexdigest()
    assert result.confidence > 0


def test_blank_submitted_answer_is_rejected():
    with pytest.raises(ValueError, match="answer_text"):
        RuleBasedAssessmentProvider().assess(
            build_question_specs()[0], "   ", "submitted"
        )
