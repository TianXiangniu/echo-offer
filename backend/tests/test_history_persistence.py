from sqlalchemy import func, select

from app.models import (
    AnswerAttempt,
    AssessmentBatch,
    AssessmentRun,
    InterviewReport,
    InterviewSession,
    OperationJob,
)


def create_test_session(client):
    profile_response = client.post(
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
    assert profile_response.status_code == 200
    session_response = client.post(
        "/api/sessions", json={"profile_id": profile_response.json()["profile_id"]}
    )
    assert session_response.status_code == 200
    session = session_response.json()
    return session["session_id"], session["questions"]


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


def test_each_completed_interview_has_its_own_persisted_report(ai_client):
    first_session_id, first_questions = create_test_session(ai_client)
    second_session_id, second_questions = create_test_session(ai_client)
    submit_all_answers(ai_client, first_session_id, first_questions, "first")
    submit_all_answers(ai_client, second_session_id, second_questions, "second")

    first_assessment = ai_client.post(f"/api/sessions/{first_session_id}/assessment")
    assert first_assessment.status_code == 200
    assert first_assessment.json()["job_status"] == "succeeded"
    assert first_assessment.json()["job_id"]
    assert ai_client.post(f"/api/sessions/{second_session_id}/assessment").status_code == 200

    with ai_client.app.state.session_factory() as db:
        reports = list(db.scalars(select(InterviewReport)))
        batches = list(db.scalars(select(AssessmentBatch)))
        runs = list(db.scalars(select(AssessmentRun)))
        assert {report.session_id for report in reports} == {
            first_session_id,
            second_session_id,
        }
        assert {report.assessment_batch_id for report in reports} == {batch.id for batch in batches}
        assert all(run.assessment_batch_id for run in runs)

        for session_id in (first_session_id, second_session_id):
            session = db.get(InterviewSession, session_id)
            assert session.current_assessment_batch_id

    history = ai_client.get("/api/interviews/history")
    assert history.status_code == 200
    assert {item["session_id"] for item in history.json()} == {
        first_session_id,
        second_session_id,
    }

    job = ai_client.get(f"/api/jobs/{first_assessment.json()['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"
    assert [event["event_type"] for event in job.json()["events"]] == [
        "queued",
        "stage",
        "completed",
    ]


def test_failed_assessment_preserves_job_error_and_answers(
    failing_ai_client, failing_ai_session_context
):
    session_id, questions = failing_ai_session_context
    submit_all_answers(failing_ai_client, session_id, questions, "failed")
    response = failing_ai_client.post(f"/api/sessions/{session_id}/assessment")

    assert response.status_code == 200
    assert response.json()["job_status"] == "failed"
    assert response.json()["job_id"]
    with failing_ai_client.app.state.session_factory() as db:
        job = db.scalar(select(OperationJob).where(OperationJob.session_id == session_id))
        assert job.status == "failed"
        assert job.error_code
        assert db.scalar(
            select(func.count(AnswerAttempt.id)).where(AnswerAttempt.session_id == session_id)
        ) == len(questions)


def test_report_endpoint_returns_persisted_report_for_completed_session(
    ai_client, ai_session_context
):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "report")
    assert ai_client.post(f"/api/sessions/{session_id}/assessment").status_code == 200

    report = ai_client.get(f"/api/sessions/{session_id}/report")

    assert report.status_code == 200
    assert report.json()["session_id"] == session_id


def test_report_and_profile_are_not_partially_committed_when_profile_update_fails(
    ai_client, ai_session_context, monkeypatch
):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "transaction")

    def fail_profile_update(*args, **kwargs):
        raise RuntimeError("profile store unavailable")

    monkeypatch.setattr("app.services.update_candidate_profile", fail_profile_update)
    response = ai_client.post(f"/api/sessions/{session_id}/assessment")

    assert response.status_code == 200
    assert response.json()["job_status"] == "failed"
    with ai_client.app.state.session_factory() as db:
        assert db.scalar(
            select(func.count(InterviewReport.id)).where(
                InterviewReport.session_id == session_id
            )
        ) == 0
        assert db.scalar(
            select(func.count(AssessmentRun.id)).where(
                AssessmentRun.status == "valid",
            )
        ) == 0
