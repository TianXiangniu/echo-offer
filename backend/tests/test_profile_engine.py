from datetime import datetime, timedelta, timezone

from app.profile_engine import SkillSample, aggregate_skill_samples, recommendation_priority


def test_profile_aggregation_weights_recent_valid_sessions_and_detects_improvement():
    now = datetime.now(timezone.utc)
    result = aggregate_skill_samples(
        [
            SkillSample(level=1, confidence=0.9, assessed_at=now - timedelta(days=30)),
            SkillSample(level=3, confidence=0.9, assessed_at=now - timedelta(days=1)),
        ],
        now=now,
    )

    assert result.current_level == 2
    assert result.valid_sample_count == 2
    assert result.trend == "improving"
    assert 0 < result.confidence <= 1


def test_recommendation_priority_marks_large_important_gap_high():
    assert recommendation_priority(
        current_level=1,
        target_level=3,
        importance_weight=1.0,
        serious_error_count=1,
        sample_count=2,
    ) == "high"


def test_recommendation_priority_marks_missing_samples_insufficient_data():
    assert recommendation_priority(
        current_level=0,
        target_level=3,
        importance_weight=1.0,
        serious_error_count=0,
        sample_count=0,
    ) == "insufficient_data"
