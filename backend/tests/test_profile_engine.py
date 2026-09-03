from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AssessmentRun, InterviewQuestion, InterviewSession, utc_now
from app.profile_engine import (
    SkillSample,
    aggregate_skill_samples,
    recommendation_priority,
    update_candidate_profile,
)


def submit_all_answers(client, session_id, questions, prefix):
    for index, question in enumerate(questions, start=1):
        response = client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "question_id": question["id"],
                "client_submission_id": f"{prefix}-{index}",
                "status": "submitted",
                "answer_text": f"第 {index} 题回答：我说明了机制、边界和工程取舍。",
            },
        )
        assert response.status_code == 200


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


def test_update_candidate_profile_prefers_lower_level_then_earlier_question(
    ai_client, ai_session_context
):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "engine-profile")
    assert ai_client.post(f"/api/sessions/{session_id}/assessment").status_code == 200

    question_ids = [item["id"] for item in questions[:2]]
    with ai_client.app.state.session_factory() as db:
        first = db.get(InterviewQuestion, question_ids[0])
        second = db.get(InterviewQuestion, question_ids[1])
        assert first is not None and second is not None
        second.knowledge_point_id = first.knowledge_point_id
        runs = list(
            db.scalars(
                select(AssessmentRun)
                .where(AssessmentRun.question_id.in_(question_ids))
                .order_by(AssessmentRun.question_id)
            )
        )
        assert len(runs) == 2
        runs[0].aggregate_level = 3
        runs[0].status = "valid"
        runs[1].aggregate_level = 1
        runs[1].status = "valid"
        db.commit()
        update_candidate_profile(db, session_id)

    with ai_client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
    summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    recommendation = next(
        item for item in summary["recommendations"] if item["skill_id"] == first.knowledge_point_id
    )
    assert recommendation["source_question_id"] == question_ids[1]

    with ai_client.app.state.session_factory() as db:
        runs = list(
            db.scalars(
                select(AssessmentRun)
                .where(AssessmentRun.question_id.in_(question_ids))
                .order_by(AssessmentRun.question_id)
            )
        )
        runs[0].aggregate_level = 2
        runs[1].aggregate_level = 2
        db.commit()
        update_candidate_profile(db, session_id)

    summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    recommendation = next(
        item for item in summary["recommendations"] if item["skill_id"] == first.knowledge_point_id
    )
    assert recommendation["source_question_id"] == question_ids[0]


def test_update_candidate_profile_ignores_invalid_runs_and_hides_archived_source_session(
    ai_client, ai_session_context
):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "engine-source")
    assert ai_client.post(f"/api/sessions/{session_id}/assessment").status_code == 200

    with ai_client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
        question = db.get(InterviewQuestion, questions[0]["id"])
        assert question is not None
        run = db.scalar(select(AssessmentRun).where(AssessmentRun.question_id == question.id))
        assert run is not None
        run.status = "pending"
        db.commit()
        update_candidate_profile(db, session_id)

    summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    recommendation = next(
        item for item in summary["recommendations"] if item["skill_id"] == question.knowledge_point_id
    )
    assert recommendation["source_session_id"] is None
    assert recommendation["source_question"] is None
    assert recommendation["source_answer_excerpt"] is None
    assert recommendation["source_level"] is None

    with ai_client.app.state.session_factory() as db:
        session = db.get(InterviewSession, session_id)
        assert session is not None
        session.archived_at = utc_now()
        db.commit()
        update_candidate_profile(db, session_id)

    summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    recommendation = next(
        item for item in summary["recommendations"] if item["skill_id"] == question.knowledge_point_id
    )
    assert recommendation["source_session_id"] is None
    assert recommendation["source_question"] == question.prompt
    assert recommendation["source_answer_excerpt"] is not None
    assert recommendation["source_level"] is not None
