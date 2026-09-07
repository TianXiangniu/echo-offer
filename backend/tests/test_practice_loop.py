from datetime import timedelta

from sqlalchemy import select

from app.models import InterviewSession, LearningRecommendation, utc_now
from tests.conftest import create_test_session


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


def _first_recommendation_id(client):
    session_id, questions = create_test_session(client)
    submit_all_answers(client, session_id, questions, "base")
    assert client.post(f"/api/sessions/{session_id}/assessment").status_code == 200
    with client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
    summary = client.get(f"/api/profiles/{profile_id}/summary").json()
    recommendation = next(
        item for item in summary["recommendations"] if item["source_question_id"]
    )
    return recommendation


def test_drill_creates_three_question_practice_session(ai_client):
    recommendation = _first_recommendation_id(ai_client)

    first = ai_client.post(f"/api/recommendations/{recommendation['id']}/drill")
    assert first.status_code == 200
    drill = first.json()
    assert drill["session_kind"] == "drill"

    # 打开中的 drill 会话直接复用（幂等）
    again = ai_client.post(f"/api/recommendations/{recommendation['id']}/drill")
    assert again.json()["session_id"] == drill["session_id"]

    view = ai_client.get(f"/api/sessions/{drill['session_id']}").json()
    assert len(view["questions"]) == 3
    assert view["progress"]["total"] == 3

    with ai_client.app.state.session_factory() as db:
        session = db.get(InterviewSession, drill["session_id"])
        assert session.session_kind == "drill"
        assert session.source_recommendation_id == recommendation["id"]
        recommendation_row = db.get(LearningRecommendation, recommendation["id"])
        assert recommendation_row.status == "in_progress"


def test_drill_assessment_records_practice_time_and_verification_completes(ai_client):
    recommendation = _first_recommendation_id(ai_client)

    drill = ai_client.post(f"/api/recommendations/{recommendation['id']}/drill").json()
    drill_view = ai_client.get(f"/api/sessions/{drill['session_id']}").json()
    submit_all_answers(ai_client, drill["session_id"], drill_view["questions"], "drill")
    assessment = ai_client.post(f"/api/sessions/{drill['session_id']}/assessment")
    assert assessment.status_code == 200

    with ai_client.app.state.session_factory() as db:
        recommendation_row = db.get(LearningRecommendation, recommendation["id"])
        assert recommendation_row.practice_completed_at is not None

    # 练习完 3 天内不能验证
    too_early = ai_client.post(f"/api/recommendations/{recommendation['id']}/verify")
    assert too_early.status_code == 409

    # 把练习时间拨回 4 天前，验证可以创建单题会话
    with ai_client.app.state.session_factory() as db:
        recommendation_row = db.get(LearningRecommendation, recommendation["id"])
        recommendation_row.practice_completed_at = utc_now() - timedelta(days=4)
        db.commit()

    verified = ai_client.post(f"/api/recommendations/{recommendation['id']}/verify")
    assert verified.status_code == 200
    verification = verified.json()
    assert verification["session_kind"] == "verification"
    view = ai_client.get(f"/api/sessions/{verification['session_id']}").json()
    assert len(view["questions"]) == 1

    submit_all_answers(ai_client, verification["session_id"], view["questions"], "verify")
    assert ai_client.post(f"/api/sessions/{verification['session_id']}/assessment").status_code == 200

    with ai_client.app.state.session_factory() as db:
        recommendation_row = db.get(LearningRecommendation, recommendation["id"])
        assert recommendation_row.status == "completed"


def test_verify_requires_prior_drill(ai_client):
    recommendation = _first_recommendation_id(ai_client)
    with ai_client.app.state.session_factory() as db:
        recommendation_row = db.get(LearningRecommendation, recommendation["id"])
        recommendation_row.practice_completed_at = None
        db.commit()

    response = ai_client.post(f"/api/recommendations/{recommendation['id']}/verify")
    assert response.status_code == 409


def test_open_drill_creates_session_without_recommendation(ai_client):
    create_test_session(ai_client)  # 确保画像存在（空库无画像时 404 是正确语义）
    response = ai_client.post("/api/practice/drill", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["session_kind"] == "drill"

    view = ai_client.get(f"/api/sessions/{body['session_id']}").json()
    assert len(view["questions"]) == 3

    # 指定知识点
    targeted = ai_client.post(
        "/api/practice/drill", json={"skill_id": "agent_runtime.tool_calling"}
    )
    assert targeted.status_code == 200
    view2 = ai_client.get(f"/api/sessions/{targeted.json()['session_id']}").json()
    assert any(
        q["knowledge_point_id"] == "agent_runtime.tool_calling"
        for q in view2["questions"]
    )

    # 未知知识点 404
    missing = ai_client.post("/api/practice/drill", json={"skill_id": "nope.nope"})
    assert missing.status_code == 404
