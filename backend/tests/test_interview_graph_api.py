from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.interview_graph_types import (
    EvidenceVerification,
    InterviewPlan,
    InterviewPlanNode,
    InterviewerTurn,
)
import app.interview_graph_api as graph_api
from app.main import create_app
from app.models import AnswerAttempt


def _plan() -> InterviewPlan:
    kinds = ["opening", "project", "architecture", "challenge", "tradeoff", "evidence"]
    return InterviewPlan(
        nodes=[
            InterviewPlanNode(
                node_id=f"node-{index}",
                kind=kind,
                goal=f"验证 {kind}",
                project_fact_ids=[],
                required_targets=[kind],
                opening_question=f"请介绍 {kind}。",
                rubric_ids=[f"rubric-{index}"],
                max_followups=2,
            )
            for index, kind in enumerate(kinds)
        ]
    )


class FakeGraphAgents:
    def plan(self, state):
        return _plan()

    def ask(self, state):
        node = state["plan"][state["current_node_index"]]
        return InterviewerTurn(
            question=node["opening_question"],
            rationale="按计划追问",
            followups_used=0,
        )

    def verify(self, state):
        node = state["plan"][state["current_node_index"]]
        return EvidenceVerification(
            claims=[state["last_answer"]["content"]],
            covered_targets=[node["kind"]],
            missing_targets=[],
            conflicts=[],
            confidence=0.9,
            route="covered",
        )


class FailingGraphAgents(FakeGraphAgents):
    def verify(self, state):
        raise RuntimeError("verifier failed")


def _client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'graph-api.db'}",
        upload_root=tmp_path / "uploads",
    )
    app.state.interview_graph_agents = FakeGraphAgents()
    return TestClient(app)


def _graph_session(client: TestClient) -> str:
    response = client.post(
        "/api/profile",
        json={
            "resume_text": "我做过一个 RAG Agent 项目。",
            "project": {
                "project_name": "企业知识库 Agent",
                "background_goal": "提升检索效率",
                "tech_stack": "Python、FastAPI、Milvus",
                "responsibilities": "负责检索链路",
                "core_solution": "混合检索和重排",
                "engineering_challenges": "召回质量",
                "failure_improvements": "增加评估和降级",
                "quantified_results": "P95 降低 20%",
            },
        },
    )
    assert response.status_code == 200
    created = client.post(
        "/api/sessions",
        json={"profile_id": response.json()["profile_id"], "mode": "graph"},
    )
    assert created.status_code == 200
    assert created.json()["questions"] == []
    return created.json()["session_id"]


def test_graph_start_resume_and_state_use_projected_runtime(tmp_path):
    with _client(tmp_path) as client:
        session_id = _graph_session(client)

        started = client.post(f"/api/sessions/{session_id}/graph/start")
        assert started.status_code == 200
        assert started.json()["status"] == "awaiting_answer"
        assert started.json()["current_question"]["prompt"]

        resumed = client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={"answer_text": "我负责召回链路。", "client_submission_id": "c1"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "awaiting_answer"

        state = client.get(f"/api/sessions/{session_id}/graph/state")
        assert state.status_code == 200
        body = state.json()
        assert body["progress"]["completed"] == 1
        assert any(item["role"] == "candidate" for item in body["timeline"])

        events = client.get(f"/api/sessions/{session_id}/graph/events")
        assert events.status_code == 200
        assert events.headers["content-type"].startswith("text/event-stream")
        assert "event: question_ready" in events.text
        assert "answer_text" not in events.text


def test_graph_resume_rejects_reused_submission_with_different_answer(tmp_path):
    with _client(tmp_path) as client:
        session_id = _graph_session(client)
        assert client.post(f"/api/sessions/{session_id}/graph/start").status_code == 200
        first = client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={"answer_text": "第一份回答", "client_submission_id": "same"},
        )
        assert first.status_code == 200

        conflict = client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={"answer_text": "不同回答", "client_submission_id": "same"},
        )
        assert conflict.status_code == 409


def test_graph_resume_rolls_back_projected_answer_when_graph_fails(tmp_path):
    with _client(tmp_path) as client:
        session_id = _graph_session(client)
        assert client.post(f"/api/sessions/{session_id}/graph/start").status_code == 200
        client.app.state.interview_graph_agents = FailingGraphAgents()

        with pytest.raises(RuntimeError, match="verifier failed"):
            client.post(
                f"/api/sessions/{session_id}/graph/resume",
                json={"answer_text": "不会被确认", "client_submission_id": "failed"},
            )

        with client.app.state.session_factory() as db:
            assert db.scalar(select(AnswerAttempt).where(AnswerAttempt.session_id == session_id)) is None


def test_graph_checkpoint_survives_app_restart(tmp_path):
    with _client(tmp_path) as first:
        session_id = _graph_session(first)
        assert first.post(f"/api/sessions/{session_id}/graph/start").status_code == 200
        assert first.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={"answer_text": "跨进程恢复", "client_submission_id": "restart-1"},
        ).status_code == 200

    with _client(tmp_path) as restarted:
        state = restarted.get(f"/api/sessions/{session_id}/graph/state")
        assert state.status_code == 200
        assert state.json()["progress"]["completed"] == 1
        assert state.json()["current_question"]["prompt"]


def test_graph_state_replays_checkpoint_events_after_projection_failure(tmp_path, monkeypatch):
    with _client(tmp_path) as client:
        session_id = _graph_session(client)
        assert client.post(f"/api/sessions/{session_id}/graph/start").status_code == 200
        original = graph_api.project_graph_event
        failed = {"value": True}

        def fail_once(db, event, *, commit=True):
            if failed["value"]:
                failed["value"] = False
                raise RuntimeError("projection unavailable")
            return original(db, event, commit=commit)

        monkeypatch.setattr(graph_api, "project_graph_event", fail_once)
        with pytest.raises(RuntimeError, match="projection unavailable"):
            client.post(
                f"/api/sessions/{session_id}/graph/resume",
                json={"answer_text": "等待补投影", "client_submission_id": "replay-1"},
            )
        monkeypatch.setattr(graph_api, "project_graph_event", original)

        repaired = client.get(f"/api/sessions/{session_id}/graph/state")
        assert repaired.status_code == 200
        with client.app.state.session_factory() as db:
            answer = db.scalar(
                select(AnswerAttempt).where(AnswerAttempt.session_id == session_id)
            )
            assert answer is not None
            assert answer.client_submission_id == "replay-1"
