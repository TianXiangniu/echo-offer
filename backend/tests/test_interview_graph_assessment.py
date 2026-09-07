from __future__ import annotations

import json

from sqlalchemy import select

from app.assessment_flow import assess_session, build_graph_assessment_payload
from app.interview_graph_projection import project_graph_event
from app.models import (
    AssessmentRun,
    CandidateKnowledgeState,
    InterviewReport,
    InterviewSession,
)


def test_graph_assessment_payload_excludes_planner_and_coach_fields():
    payload = build_graph_assessment_payload(
        {
            "status": "completed",
            "plan": [
                {
                    "node_id": "architecture",
                    "kind": "architecture",
                    "rubric_ids": ["mechanism"],
                    "required_targets": ["tradeoff"],
                }
            ],
            "messages": [
                {"role": "interviewer", "node_id": "architecture", "content": "怎么设计？"},
                {"role": "candidate", "node_id": "architecture", "content": "我会先拆分边界。"},
            ],
            "coverage": {"architecture": ["tradeoff"]},
        }
    )
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload[0]["plan_node_id"] == "architecture"
    assert payload[0]["answer"] == "我会先拆分边界。"
    assert "expected_grade" not in serialized
    assert "coach" not in serialized
    assert "practice_feedback" not in serialized


def test_graph_assessment_persists_plan_node_metadata(ai_client):
    profile = ai_client.post(
        "/api/profile",
        json={
            "resume_text": "我做过一个 RAG Agent 项目。",
            "project": {
                "project_name": "知识库 Agent",
                "background_goal": "提升检索效率",
                "tech_stack": "Python、FastAPI",
                "responsibilities": "负责检索链路",
                "core_solution": "混合检索",
                "engineering_challenges": "召回质量",
                "failure_improvements": "增加评估",
                "quantified_results": "P95 降低 20%",
            },
        },
    ).json()
    session = ai_client.post(
        "/api/sessions",
        json={"profile_id": profile["profile_id"], "mode": "graph"},
    ).json()
    session_id = session["session_id"]

    with ai_client.app.state.session_factory() as db:
        graph_session = db.get(InterviewSession, session_id)
        project_graph_event(
            db,
            {
                "session_id": session_id,
                "graph_step_id": "question:node-0-0",
                "event_kind": "question_ready",
                "payload": {
                    "question_id": "graph-node-0-0",
                    "node_id": "node-0",
                    "kind": "opening",
                    "text": "请介绍项目。",
                    "order": 0,
                },
            },
        )
        project_graph_event(
            db,
            {
                "session_id": session_id,
                "graph_step_id": "answer:node-0-0",
                "event_kind": "candidate_answer",
                "payload": {
                    "question_id": "graph-node-0-0",
                    "client_submission_id": "answer-1",
                    "answer_text": "我负责检索链路。",
                },
            },
        )
        project_graph_event(
            db,
            {
                "session_id": session_id,
                "graph_step_id": "completed",
                "event_kind": "completed",
                "payload": {"status": "completed"},
            },
        )

    with ai_client.app.state.session_factory() as db:
        result = assess_session(db, session_id, ai_client.app.state.assessment_provider)
    assert result["status"] == "valid"

    with ai_client.app.state.session_factory() as db:
        run = db.scalar(select(AssessmentRun).where(AssessmentRun.question_id == "graph-node-0-0"))
        assert run is not None
        assert run.plan_node_id == "node-0"
        skills = list(db.scalars(select(CandidateKnowledgeState)))
        assert any(skill.skill_id == "project.ownership_and_context" for skill in skills)
        report = db.scalar(select(InterviewReport).where(InterviewReport.session_id == session_id))
        assert report is not None
        report_payload = json.loads(report.report_json)
        assert report_payload["transcript"][0]["plan_node_id"] == "node-0"
