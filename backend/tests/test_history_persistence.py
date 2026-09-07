from sqlalchemy import func, select

from app.rubrics import rubric_from_dict
from app.models import (
    AnswerAttempt,
    AssessmentBatch,
    AssessmentRun,
    InterviewQuestion,
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
    event_types = [event["event_type"] for event in job.json()["events"]]
    assert event_types[0] == "queued"
    assert event_types[-1] == "completed"
    assert event_types.count("stage") >= 1


def test_failed_assessment_preserves_job_error_and_answers(
    failing_ai_client, failing_ai_session_context
):
    session_id, questions = failing_ai_session_context
    submit_all_answers(failing_ai_client, session_id, questions, "failed")
    response = failing_ai_client.post(f"/api/sessions/{session_id}/assessment")

    assert response.status_code == 200
    # 一批失败、其余成功时结果保留为 partial，错误信息随任务保留，可重试补齐
    assert response.json()["job_status"] == "partial"
    assert response.json()["job_id"]
    assert response.json()["job_error_code"]
    with failing_ai_client.app.state.session_factory() as db:
        job = db.scalar(select(OperationJob).where(OperationJob.session_id == session_id))
        assert job.status == "partial"
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

    monkeypatch.setattr(
        "app.assessment_flow.update_candidate_profile", fail_profile_update
    )
    response = ai_client.post(f"/api/sessions/{session_id}/assessment")

    assert response.status_code == 200
    assert response.json()["job_status"] == "failed"
    with ai_client.app.state.session_factory() as db:
        assert db.scalar(
            select(func.count(InterviewReport.id)).where(
                InterviewReport.session_id == session_id
            )
        ) == 0


def test_session_creation_freezes_project_reference_facts_into_rubric(client):
    import json

    session_id, _ = create_test_session(client)

    with client.app.state.session_factory() as db:
        questions = list(
            db.scalars(
                select(InterviewQuestion).where(InterviewQuestion.session_id == session_id)
            )
        )
        assert questions
        facts_by_knowledge_point = {}
        for question in questions:
            rubric = rubric_from_dict(json.loads(question.rubric_json))
            facts_by_knowledge_point = facts_by_knowledge_point or {}
            facts_by_knowledge_point[question.knowledge_point_id] = rubric.reference_facts

    assert facts_by_knowledge_point["project.ownership_and_context"] == (
        "降低内部知识检索成本",
        "负责检索链路、接口和监控",
    )
    assert facts_by_knowledge_point["project.architecture_tradeoffs"] == (
        "查询改写、混合检索、重排和答案引用",
        "召回质量和线上延迟平衡",
    )
    assert facts_by_knowledge_point["project.evaluation_and_reproducibility"] == (
        "命中率提升 18%，P95 延迟下降 25%",
        "增加超时、降级和评估集",
    )
    # 动态抽题下固定题知识点不固定，但每道固定题都必须带参考事实
    for knowledge_point_id, facts in facts_by_knowledge_point.items():
        if knowledge_point_id.startswith("project."):
            continue
        assert len(facts) >= 3, knowledge_point_id


def test_consecutive_sessions_avoid_recently_used_templates(client):
    first_id, first_questions = create_test_session(client)
    second_id, second_questions = create_test_session(client)

    first_templates = {question.get("template_id") for question in first_questions} - {None}
    second_templates = {question.get("template_id") for question in second_questions} - {None}

    assert first_templates and second_templates
    assert len(first_templates) == 5
    assert not first_templates & second_templates


def test_report_transcript_contains_full_q_and_a(ai_client):
    session_id, questions = create_test_session(ai_client)
    for index, question in enumerate(questions, start=1):
        ai_client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "question_id": question["id"],
                "client_submission_id": f"tr-{index}",
                "status": "submitted" if index > 1 else "skipped",
                "answer_text": f"第 {index} 题完整回答：说明了机制、边界与取舍的全部内容。",
            },
        )
    assert ai_client.post(f"/api/sessions/{session_id}/assessment").status_code == 200

    report = ai_client.get(f"/api/sessions/{session_id}/report").json()
    transcript = report["transcript"]
    assert len(transcript) == len(questions)
    first = next(item for item in transcript if item["order"] == 1)
    assert first["prompt"] == questions[0]["prompt"]
    assert first["status"] == "skipped"
    answered = next(item for item in transcript if item["order"] == 2)
    assert answered["answer_text"].startswith("第 2 题完整回答")
    assert answered["level"] is not None
