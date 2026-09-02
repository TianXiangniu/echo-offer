from datetime import timedelta

from sqlalchemy import func, select

from app.models import AnswerAttempt, InterviewSession, utc_now


def create_history_session(client):
    profile = client.post(
        "/api/profile",
        json={
            "resume_text": "我做过一个面向企业知识库的 RAG Agent 项目。",
            "project": {
                "project_name": "企业知识库问答 Agent",
                "background_goal": "降低内部知识检索成本",
                "tech_stack": "Python、FastAPI、Milvus、DeepSeek",
                "responsibilities": "负责检索链路、接口和监控",
                "core_solution": "查询改写、混合检索、重排和答案引用",
                "engineering_challenges": "召回质量和线上延迟平衡",
                "failure_improvements": "增加超时、降级和评估集",
                "quantified_results": "命中率提升 18%，P95 延迟下降 25%",
            },
        },
    )
    assert profile.status_code == 200
    session = client.post("/api/sessions", json={"profile_id": profile.json()["profile_id"]})
    assert session.status_code == 200
    body = session.json()
    return body["session_id"], body["questions"]


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


def test_history_contains_project_name_and_null_report_counts(ai_client):
    session_id, _ = create_history_session(ai_client)

    response = ai_client.get("/api/interviews/history")

    assert response.status_code == 200
    item = next(row for row in response.json() if row["session_id"] == session_id)
    assert item["project_name"] == "企业知识库问答 Agent"
    assert item["completed"] == 0
    assert item["total"] == 8
    assert item["strength_count"] is None
    assert item["gap_count"] is None


def test_history_returns_report_summary_counts(ai_client):
    session_id, questions = create_history_session(ai_client)
    submit_all_answers(ai_client, session_id, questions, "history-summary")
    assert ai_client.post(f"/api/sessions/{session_id}/assessment").status_code == 200

    report = ai_client.get(f"/api/sessions/{session_id}/report").json()
    item = next(
        row for row in ai_client.get("/api/interviews/history").json()
        if row["session_id"] == session_id
    )

    assert item["strength_count"] == len(report["strengths"])
    assert item["gap_count"] == len(report["gaps"])


def test_history_is_ordered_by_newest_session(ai_client):
    older_id, _ = create_history_session(ai_client)
    newer_id, _ = create_history_session(ai_client)

    with ai_client.app.state.session_factory() as db:
        older = db.get(InterviewSession, older_id)
        newer = db.get(InterviewSession, newer_id)
        older.created_at = utc_now() - timedelta(minutes=1)
        newer.created_at = utc_now()
        db.commit()

    rows = ai_client.get("/api/interviews/history").json()
    returned_ids = [row["session_id"] for row in rows]
    assert returned_ids.index(newer_id) < returned_ids.index(older_id)


def test_delete_hides_session_but_preserves_answers(ai_client):
    session_id, questions = create_history_session(ai_client)
    answer = ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "archive-answer",
            "status": "submitted",
            "answer_text": "我负责了检索链路。",
        },
    )
    assert answer.status_code == 200

    response = ai_client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 204
    assert all(row["session_id"] != session_id for row in ai_client.get("/api/interviews/history").json())
    assert ai_client.get(f"/api/sessions/{session_id}").status_code == 404
    assert ai_client.delete(f"/api/sessions/{session_id}").status_code == 404

    with ai_client.app.state.session_factory() as db:
        session = db.get(InterviewSession, session_id)
        assert session.archived_at is not None
        assert db.scalar(
            select(func.count(AnswerAttempt.id)).where(AnswerAttempt.session_id == session_id)
        ) == 1


def test_archived_session_cannot_be_read_or_changed(ai_client):
    session_id, questions = create_history_session(ai_client)
    assert ai_client.delete(f"/api/sessions/{session_id}").status_code == 204

    assert ai_client.get(f"/api/sessions/{session_id}/report").status_code == 404
    assert ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "archived-answer",
            "status": "submitted",
            "answer_text": "不能继续修改。",
        },
    ).status_code == 404
    assert ai_client.post(f"/api/sessions/{session_id}/assessment").status_code == 404
