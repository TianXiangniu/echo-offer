from io import BytesIO
import json
from uuid import uuid4

import pymupdf
from docx import Document
from sqlalchemy import select

from app.models import Resume, ResumeProjectQuestion, ResumeSource, User
from app.schemas import AgentProjectAnalysisResponse


PROJECT = {
    "project_name": "知识库 Agent",
    "background_goal": "提升检索效率",
    "tech_stack": "Python、FastAPI、向量数据库",
    "responsibilities": "负责后端和评估",
    "core_solution": "混合检索和重排",
    "engineering_challenges": "召回质量",
    "failure_improvements": "增加监控和降级",
    "quantified_results": "P95 降低 20%",
}


class StaticProjectAnalysisProvider:
    def __init__(self, result):
        self.result = result

    def analyze(self, resume_text):
        return self.result


def make_pdf_bytes():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(72, 72, 520, 180),
        "Project experience: built a retrieval augmented generation agent for enterprise search.",
    )
    try:
        return document.tobytes()
    finally:
        document.close()


def make_docx_bytes():
    document = Document()
    document.add_paragraph(
        "工作经历：负责企业知识库 Agent 后端开发，设计检索链路并维护线上稳定性。"
    )
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Python"
    table.rows[0].cells[1].text = "FastAPI"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_profile_and_session_creation_have_fixed_shape(client):
    profile_response = client.post(
        "/api/profile",
        json={
            "resume_text": "我负责过一个 RAG Agent 项目。",
            "project": {
                "project_name": "知识库 Agent",
                "background_goal": "提升检索效率",
                "tech_stack": "Python、FastAPI、向量数据库",
                "responsibilities": "负责后端和评估",
                "core_solution": "混合检索和重排",
                "engineering_challenges": "召回质量",
                "failure_improvements": "增加监控和降级",
                "quantified_results": "P95 降低 20%",
            },
        },
    )

    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["user_id"] == "local-user"
    assert profile["project_version"] == 1
    assert len(profile["resume_text_hash"]) == 64

    session_response = client.post(
        "/api/sessions", json={"profile_id": profile["profile_id"]}
    )

    assert session_response.status_code == 200
    session = session_response.json()
    assert len(session["questions"]) == 8
    assert [question["category"] for question in session["questions"]].count("project") == 3
    assert [question["category"] for question in session["questions"]].count("agent") == 3
    assert [question["category"] for question in session["questions"]].count("reliability") == 2
    assert [question["category"] for question in session["questions"]] == [
        "project", "project", "project",
        "agent", "agent", "agent",
        "reliability", "reliability",
    ]
    assert [question["is_anchor"] for question in session["questions"]] == [
        True, False, False,
        True, False, False,
        True, False,
    ]


def test_custom_project_questions_are_grouped_before_fixed_questions(client):
    profile_response = client.post(
        "/api/profile",
        json={"resume_text": "简历文本", "project": PROJECT},
    )
    assert profile_response.status_code == 200
    profile_id = profile_response.json()["profile_id"]

    with client.app.state.session_factory() as db:
        for order, prompt in enumerate(["项目题一", "项目题二", "项目题三"], start=1):
            db.add(
                ResumeProjectQuestion(
                    id=str(uuid4()),
                    resume_project_id=profile_id,
                    order=order,
                    prompt=prompt,
                    knowledge_point_id=f"project.custom.{order}",
                    signals_json=json.dumps(["项目", "证据"], ensure_ascii=False),
                    source="user_edited",
                )
            )
        db.commit()

    session_response = client.post("/api/sessions", json={"profile_id": profile_id})

    assert session_response.status_code == 200
    questions = session_response.json()["questions"]
    assert [question["category"] for question in questions] == [
        "project", "project", "project",
        "agent", "agent", "agent",
        "reliability", "reliability",
    ]
    assert [question["prompt"] for question in questions[:3]] == [
        "项目题一", "项目题二", "项目题三"
    ]
    assert [question["is_anchor"] for question in questions] == [
        True, False, False,
        True, False, False,
        True, False,
    ]


def test_parse_pdf_persists_resume_source(client):
    response = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "pdf"
    assert body["unit_count"] == 1
    assert body["extracted_text"]
    assert body["character_count"] == len(body["extracted_text"])

    with client.app.state.session_factory() as db:
        assert len(list(db.scalars(select(Resume)))) == 1
        sources = list(db.scalars(select(ResumeSource)))
        assert len(sources) == 1
        assert sources[0].source_type == "pdf"
        assert (client.app.state.upload_root / sources[0].stored_path).exists()


def test_parse_docx_returns_extracted_text(client):
    response = client.post(
        "/api/resumes/parse",
        files={
            "file": (
                "resume.docx",
                make_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["source_type"] == "docx"
    assert "工作经历" in response.json()["extracted_text"]
    assert "Python" in response.json()["extracted_text"]


def test_parse_returns_stable_file_errors(client):
    unsupported = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.txt", b"plain text", "text/plain")},
    )
    invalid_signature = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", b"not a pdf", "application/pdf")},
    )
    too_large = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
    )

    assert unsupported.status_code == 415
    assert unsupported.json()["code"] == "unsupported_file_type"
    assert invalid_signature.status_code == 422
    assert invalid_signature.json()["code"] == "invalid_file_signature"
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "file_too_large"


def test_stream_analysis_route_returns_sse_events(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    analysis = AgentProjectAnalysisResponse.model_validate(
        {
            "project": PROJECT,
            "selection_reason": "简历中包含 Agent 项目经历。",
            "confidence": 0.8,
            "evidence": [
                {
                    "field": "background_goal",
                    "quote": "Project experience: built a retrieval augmented generation agent for enterprise search.",
                }
            ],
            "questions": [
                {
                    "prompt": "你在项目中具体负责了什么？",
                    "knowledge_point_id": "project.ownership_and_context",
                    "signals": ["职责", "项目"],
                },
                {
                    "prompt": "为什么选择这套技术方案？",
                    "knowledge_point_id": "project.architecture_tradeoffs",
                    "signals": ["方案", "取舍"],
                },
                {
                    "prompt": "你如何验证项目效果？",
                    "knowledge_point_id": "project.evaluation_and_reproducibility",
                    "signals": ["效果", "验证"],
                },
            ],
            "missing_information": [],
        }
    )
    client.app.state.project_analysis_provider = StaticProjectAnalysisProvider(analysis)

    with client.stream(
        "POST",
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis/stream",
        json={"resume_text": parsed["extracted_text"]},
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: result" in body
    assert body.index("event: result") < body.index("event: done")


def test_profile_reuses_parsed_resume_and_saves_final_text(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    final_text = parsed["extracted_text"] + "\n用户确认补充：负责线上故障复盘。"

    response = client.post(
        "/api/profile",
        json={"resume_id": parsed["resume_id"], "resume_text": final_text, "project": PROJECT},
    )

    assert response.status_code == 200
    with client.app.state.session_factory() as db:
        resumes = list(db.scalars(select(Resume)))
        assert len(resumes) == 1
        assert resumes[0].resume_text == final_text


def test_profile_rejects_resume_owned_by_another_user(client):
    with client.app.state.session_factory() as db:
        db.add(User(id="other-user"))
        db.add(
            Resume(
                id="other-resume",
                user_id="other-user",
                resume_text="这是一份用于权限测试的简历文本。",
                text_hash="0" * 64,
            )
        )
        db.commit()

    response = client.post(
        "/api/profile",
        json={"resume_id": "other-resume", "resume_text": "修改后的文本", "project": PROJECT},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "resume_owner_conflict"


def test_session_read_returns_current_question_and_progress(client, session_context):
    session_id, questions = session_context

    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    view = response.json()
    assert view["session_id"] == session_id
    assert view["status"] == "in_progress"
    assert view["current_question"]["id"] == questions[0]["id"]
    assert view["progress"] == {"completed": 0, "total": 8}


def test_duplicate_submission_returns_one_answer_and_one_observation(
    client, session_context
):
    session_id, questions = session_context
    payload = {
        "question_id": questions[0]["id"],
        "client_submission_id": "stable-1",
        "status": "submitted",
        "answer_text": "我负责业务目标和检索链路，结果通过评估集验证并降低了延迟。",
    }

    first = client.post(f"/api/sessions/{session_id}/answers", json=payload)
    second = client.post(f"/api/sessions/{session_id}/answers", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["answer"]["id"] == second.json()["answer"]["id"]
    assert first.json()["observation"]["id"] == second.json()["observation"]["id"]


def test_same_submission_id_with_different_payload_returns_409(client, session_context):
    session_id, questions = session_context
    first_payload = {
        "question_id": questions[0]["id"],
        "client_submission_id": "stable-conflict",
        "status": "submitted",
        "answer_text": "第一版回答。",
    }
    second_payload = {**first_payload, "answer_text": "不同内容的第二版回答。"}

    assert client.post(f"/api/sessions/{session_id}/answers", json=first_payload).status_code == 200
    conflict = client.post(f"/api/sessions/{session_id}/answers", json=second_payload)

    assert conflict.status_code == 409


def test_unknown_and_skipped_have_distinct_evaluation_behavior(client, session_context):
    session_id, questions = session_context
    unknown = client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "unknown-1",
            "status": "explicit_unknown",
            "answer_text": "不知道",
        },
    )
    skipped = client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[1]["id"],
            "client_submission_id": "skip-1",
            "status": "skipped",
            "answer_text": "",
        },
    )

    assert unknown.status_code == 200
    assert unknown.json()["observation"]["level"] == 0
    assert skipped.status_code == 200
    assert skipped.json()["observation"] is None


def test_blank_submitted_answer_is_rejected(client, session_context):
    session_id, questions = session_context
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "blank-1",
            "status": "submitted",
            "answer_text": "   ",
        },
    )

    assert response.status_code == 422


def test_report_aggregates_without_uncalibrated_score(client, session_context):
    session_id, questions = session_context
    for index, question in enumerate([questions[0], questions[3]]):
        response = client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "question_id": question["id"],
                "client_submission_id": f"report-{index}",
                "status": "submitted",
                "answer_text": "我会结合机制、边界、监控和评估集分析问题并验证结果。",
            },
        )
        assert response.status_code == 200

    report_response = client.get(f"/api/sessions/{session_id}/report")

    assert report_response.status_code == 200
    report = report_response.json()
    assert report["completion"] == {"completed": 2, "total": 8}
    assert report["anchor_coverage"] == {"answered": 2, "total": 3}
    assert 0 < report["coverage"] < 1
    assert report["valid_evidence_count"] == 2
    assert "score_100" not in report


def test_ai_assessment_is_saved_per_rubric_and_aggregated(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    response = ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "ai-1",
            "status": "submitted",
            "answer_text": "我先验证方案，再解释机制，并说明边界和延迟取舍。",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assessment"]["status"] == "valid"
    assert body["assessment"]["level"] == 3
    assert len(body["assessment"]["rubric_items"]) == 4


def test_provider_error_preserves_answer_and_same_payload_retries(
    failing_ai_client, failing_ai_session_context
):
    session_id, questions = failing_ai_session_context
    payload = {
        "question_id": questions[0]["id"],
        "client_submission_id": "ai-retry-1",
        "status": "submitted",
        "answer_text": "回答必须在模型失败后继续保留。",
    }

    first = failing_ai_client.post(f"/api/sessions/{session_id}/answers", json=payload)
    second = failing_ai_client.post(f"/api/sessions/{session_id}/answers", json=payload)

    assert first.status_code == 200
    assert first.json()["answer"]["answer_text"] == payload["answer_text"]
    assert first.json()["assessment"]["status"] == "pending"
    assert first.json()["assessment"]["error_code"] == "system_error"
    assert second.status_code == 200
    assert second.json()["answer"]["id"] == first.json()["answer"]["id"]
    assert second.json()["assessment"]["status"] == "valid"


def test_provider_error_code_is_preserved(
    provider_error_ai_client, provider_error_ai_session_context
):
    session_id, questions = provider_error_ai_session_context
    response = provider_error_ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "ai-provider-error-1",
            "status": "submitted",
            "answer_text": "模型超时后仍然应该保留可重试状态。",
        },
    )

    assert response.status_code == 200
    assessment = response.json()["assessment"]
    assert assessment["status"] == "pending"
    assert assessment["error_code"] == "provider_timeout"


def test_invalid_rubric_evidence_is_preserved_but_excluded_from_report(
    invalid_ai_client, invalid_ai_session_context
):
    session_id, questions = invalid_ai_session_context
    response = invalid_ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "ai-invalid-1",
            "status": "submitted",
            "answer_text": "这条回答的证据需要被保留并审计。",
        },
    )

    assert response.status_code == 200
    assessment = response.json()["assessment"]
    assert assessment["status"] == "invalid"
    assert any(item["validity"] == "invalid" for item in assessment["rubric_items"])

    report = invalid_ai_client.get(f"/api/sessions/{session_id}/report").json()
    assert report["valid_evidence_count"] == 0
    assert report["assessment_status_counts"]["invalid"] == 1


def test_report_exposes_valid_ai_rubric_evidence(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    response = ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "ai-report-rubric-1",
            "status": "submitted",
            "answer_text": "报告应该能够回溯每个 Rubric 项的证据。",
        },
    )
    assert response.status_code == 200

    report = ai_client.get(f"/api/sessions/{session_id}/report").json()

    assert len(report["rubric_items"]) == 4
    assert {item["rubric_id"] for item in report["rubric_items"]} == {
        "correctness",
        "mechanism",
        "scenario",
        "engineering",
    }
