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
        runs_by_question_id = {run.question_id: run for run in runs}
        assert set(runs_by_question_id) == set(question_ids)
        runs_by_question_id[question_ids[0]].aggregate_level = 3
        runs_by_question_id[question_ids[0]].status = "valid"
        runs_by_question_id[question_ids[1]].aggregate_level = 1
        runs_by_question_id[question_ids[1]].status = "valid"
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
        runs_by_question_id = {run.question_id: run for run in runs}
        assert set(runs_by_question_id) == set(question_ids)
        runs_by_question_id[question_ids[0]].aggregate_level = 2
        runs_by_question_id[question_ids[1]].aggregate_level = 2
        db.commit()
        update_candidate_profile(db, session_id)

    summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    recommendation = next(
        item for item in summary["recommendations"] if item["skill_id"] == first.knowledge_point_id
    )
    assert recommendation["source_question_id"] == question_ids[0]


def test_update_candidate_profile_keeps_source_when_later_session_skips_skill(
    ai_client, ai_session_context
):
    first_session_id, first_questions = ai_session_context
    submit_all_answers(ai_client, first_session_id, first_questions, "first-source")
    assert ai_client.post(f"/api/sessions/{first_session_id}/assessment").status_code == 200

    with ai_client.app.state.session_factory() as db:
        first_session = db.get(InterviewSession, first_session_id)
        assert first_session is not None
        profile_id = first_session.profile_id
        resume_project_id = first_session.resume_project_id

    first_summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    first_source = next(
        item
        for item in first_summary["recommendations"]
        if item["source_question_id"] is not None
    )

    second_session_response = ai_client.post(
        "/api/sessions", json={"profile_id": resume_project_id}
    )
    assert second_session_response.status_code == 200
    second_session = second_session_response.json()
    second_session_id = second_session["session_id"]
    for index, question in enumerate(second_session["questions"], start=1):
        skips_source_skill = question["knowledge_point_id"] == first_source["skill_id"]
        response = ai_client.post(
            f"/api/sessions/{second_session_id}/answers",
            json={
                "question_id": question["id"],
                "client_submission_id": f"second-source-{index}",
                "status": "skipped" if skips_source_skill else "submitted",
                "answer_text": "" if skips_source_skill else "我说明了机制、边界和工程取舍。",
            },
        )
        assert response.status_code == 200
    assert ai_client.post(f"/api/sessions/{second_session_id}/assessment").status_code == 200

    second_summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    second_source = next(
        item
        for item in second_summary["recommendations"]
        if item["skill_id"] == first_source["skill_id"]
    )
    for field in (
        "source_session_id",
        "source_question_id",
        "source_question",
        "source_answer_excerpt",
        "source_level",
    ):
        assert second_source[field] == first_source[field]


def test_update_candidate_profile_switches_source_to_later_valid_session(
    ai_client, ai_session_context
):
    first_session_id, first_questions = ai_session_context
    submit_all_answers(ai_client, first_session_id, first_questions, "first-valid-source")
    assert ai_client.post(f"/api/sessions/{first_session_id}/assessment").status_code == 200

    with ai_client.app.state.session_factory() as db:
        first_session = db.get(InterviewSession, first_session_id)
        assert first_session is not None
        profile_id = first_session.profile_id
        resume_project_id = first_session.resume_project_id

    first_summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    first_source = next(
        item
        for item in first_summary["recommendations"]
        if item["source_question_id"] is not None
    )

    second_session_response = ai_client.post(
        "/api/sessions", json={"profile_id": resume_project_id}
    )
    assert second_session_response.status_code == 200
    second_session = second_session_response.json()
    second_session_id = second_session["session_id"]
    submit_all_answers(
        ai_client,
        second_session_id,
        second_session["questions"],
        "second-valid-source",
    )
    assert ai_client.post(f"/api/sessions/{second_session_id}/assessment").status_code == 200

    second_source_questions = [
        question
        for question in second_session["questions"]
        if question["knowledge_point_id"] == first_source["skill_id"]
    ]
    assert second_source_questions
    expected_question = min(second_source_questions, key=lambda question: question["order"])
    with ai_client.app.state.session_factory() as db:
        runs = list(
            db.scalars(
                select(AssessmentRun).where(
                    AssessmentRun.question_id.in_(
                        question["id"] for question in second_source_questions
                    )
                )
            )
        )
        assert runs
        for run in runs:
            run.aggregate_level = 1
            run.status = "valid"
        db.commit()
        update_candidate_profile(db, second_session_id)

    second_summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    second_source = next(
        item
        for item in second_summary["recommendations"]
        if item["skill_id"] == first_source["skill_id"]
    )
    assert second_source["source_session_id"] == second_session_id
    assert second_source["source_question_id"] == expected_question["id"]
    assert second_source["source_question"] == expected_question["prompt"]
    assert second_source["source_level"] == 1


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
        for status in ("pending", "invalid", "rejected"):
            run.status = status
            db.commit()
            update_candidate_profile(db, session_id)

            summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
            recommendation = next(
                item
                for item in summary["recommendations"]
                if item["skill_id"] == question.knowledge_point_id
            )
            assert recommendation["source_session_id"] is None
            assert recommendation["source_question_id"] is None
            assert recommendation["source_question"] is None
            assert recommendation["source_answer_excerpt"] is None
            assert recommendation["source_level"] is None

        run.status = "valid"
        db.commit()
        update_candidate_profile(db, session_id)

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


def test_drill_samples_cannot_grind_level_up_but_verification_can():
    from app.profile_engine import SkillSample, aggregate_skill_samples

    now = datetime.now(timezone.utc)

    # 初始：一次正式面试 2 分。之后连刷 3 次 drill 全 4 分。
    drills = [
        SkillSample(
            level=4,
            confidence=0.9,
            assessed_at=now - timedelta(days=1 + index),
            weight=0.5,
        )
        for index in range(3)
    ]
    grinded = aggregate_skill_samples(
        [SkillSample(level=2, confidence=0.9, assessed_at=now, weight=1.0), *drills]
    )
    assert grinded.current_level < 4

    # 一次 verification 4 分（权重 1.2）应显著抬升等级
    verified = aggregate_skill_samples(
        [
            SkillSample(level=4, confidence=0.9, assessed_at=now, weight=1.2),
            SkillSample(level=2, confidence=0.9, assessed_at=now - timedelta(days=5), weight=1.0),
        ]
    )
    assert verified.current_level >= 3


def test_summary_contains_hard_data(ai_client):
    from tests.conftest import create_test_session

    def submit(client, session_id, questions, prefix):
        for index, question in enumerate(questions, start=1):
            client.post(
                f"/api/sessions/{session_id}/answers",
                json={
                    "question_id": question["id"],
                    "client_submission_id": f"{prefix}-{index}",
                    "status": "submitted",
                    "answer_text": f"第 {index} 题：机制、边界、取舍都讲清楚。",
                },
            )

    session_id, questions = create_test_session(ai_client)
    submit(ai_client, session_id, questions, "sum")
    ai_client.post(f"/api/sessions/{session_id}/assessment")
    with ai_client.app.state.session_factory() as db:
        from app.models import InterviewSession as IS

        profile_id = db.get(IS, session_id).profile_id
    body = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    assert "已积累" in body["summary"] and "次有效回答" in body["summary"]
