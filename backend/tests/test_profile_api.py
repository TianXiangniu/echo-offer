from sqlalchemy import func, select

from app.models import CandidateProfile, InterviewQuestion, InterviewSession, ProfileSnapshot


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


def test_valid_batch_updates_profile_and_recommendations(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "profile")

    assessment = ai_client.post(f"/api/sessions/{session_id}/assessment")
    assert assessment.status_code == 200

    with ai_client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
    response = ai_client.get(f"/api/profiles/{profile_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["profile_id"] == profile_id
    assert body["skills"]
    assert "recommendations" in body

    source = next(
        item for item in body["recommendations"] if item["source_question_id"] is not None
    )
    assert source["source_session_id"] == session_id
    assert source["source_level"] in {0, 1, 2, 3, 4}
    assert len(source["source_answer_excerpt"]) <= 240

    answer_index = next(
        index
        for index, question in enumerate(questions, start=1)
        if question["id"] == source["source_question_id"]
    )
    answer_text = f"第 {answer_index} 题回答：我说明了机制、边界和工程取舍。"
    assert answer_text.startswith(source["source_answer_excerpt"])

    with ai_client.app.state.session_factory() as db:
        source_question = db.get(InterviewQuestion, source["source_question_id"])
        assert source_question is not None
        assert source["source_question"] == source_question.prompt


def test_failed_batch_does_not_update_profile(
    failing_ai_client, failing_ai_session_context
):
    session_id, questions = failing_ai_session_context
    submit_all_answers(failing_ai_client, session_id, questions, "failed-profile")
    failing_ai_client.post(f"/api/sessions/{session_id}/assessment")

    with failing_ai_client.app.state.session_factory() as db:
        session = db.get(InterviewSession, session_id)
        assert session.profile_id is not None
        assert db.scalar(select(func.count(ProfileSnapshot.id))) == 0

    body = failing_ai_client.get(f"/api/profiles/{session.profile_id}/summary").json()
    assert body["skills"] == []


def test_profile_history_returns_snapshots_in_newest_first_order(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "history-profile")
    ai_client.post(f"/api/sessions/{session_id}/assessment")

    with ai_client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
    response = ai_client.get(f"/api/profiles/{profile_id}/history")

    assert response.status_code == 200
    assert [item["version"] for item in response.json()] == [1]


def test_recommendation_status_can_be_updated(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "recommendation-status")
    ai_client.post(f"/api/sessions/{session_id}/assessment")

    with ai_client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
    summary = ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    recommendation_id = summary["recommendations"][0]["id"]

    response = ai_client.patch(
        f"/api/recommendations/{recommendation_id}",
        json={"status": "in_progress"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
