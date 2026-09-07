from app.workflow_common import calculate_score_100


def test_score_100_averages_valid_answer_scores_and_rounds_half_up():
    score = calculate_score_100(
        {"question-1": 75.0, "question-2": 50.0},
        total_questions=2,
        completed_question_ids={"question-1", "question-2"},
        expected_scored_question_ids={"question-1", "question-2"},
    )

    assert score == 63


def test_score_100_is_unavailable_when_interview_or_assessment_is_incomplete():
    assert calculate_score_100(
        {"question-1": 75.0},
        total_questions=2,
        completed_question_ids={"question-1"},
        expected_scored_question_ids={"question-1"},
    ) is None
    assert calculate_score_100(
        {"question-1": 75.0},
        total_questions=2,
        completed_question_ids={"question-1", "question-2"},
        expected_scored_question_ids={"question-1", "question-2"},
    ) is None


def test_score_100_ignores_skipped_questions_but_requires_all_attempts():
    score = calculate_score_100(
        {"question-1": 75.0, "question-2": 50.0},
        total_questions=3,
        completed_question_ids={"question-1", "question-2", "question-3"},
        expected_scored_question_ids={"question-1", "question-2"},
    )

    assert score == 63
