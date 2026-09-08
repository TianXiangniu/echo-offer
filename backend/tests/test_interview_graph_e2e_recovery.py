from sqlalchemy import func, select
from fastapi.testclient import TestClient

from app.interview_graph_types import EvidenceVerification, InterviewPlan, InterviewPlanNode, InterviewerTurn
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
                rubric_ids=["correctness", "mechanism", "scenario", "engineering"],
                max_followups=2,
            )
            for index, kind in enumerate(kinds)
        ]
    )


class StableGraphAgents:
    def plan(self, state):
        return _plan()

    def ask(self, state):
        node = state["plan"][state["current_node_index"]]
        return InterviewerTurn(
            question=node["opening_question"],
            rationale="继续当前节点",
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


def graph_client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'graph-e2e.db'}",
        upload_root=tmp_path / "uploads",
    )
    app.state.interview_graph_agents = StableGraphAgents()
    client = TestClient(app)
    profile = client.post(
        "/api/profile",
        json={
            "resume_text": "我做过一个 RAG Agent 项目。",
            "project": {
                "project_name": "企业知识库 Agent",
                "background_goal": "降低内部知识检索成本",
                "tech_stack": "Python、FastAPI、Milvus",
                "responsibilities": "负责检索链路",
                "core_solution": "混合检索和重排",
                "engineering_challenges": "召回质量",
                "failure_improvements": "增加评估和降级",
                "quantified_results": "P95 降低 20%",
            },
        },
    )
    assert profile.status_code == 200
    session = client.post(
        "/api/sessions",
        json={"profile_id": profile.json()["profile_id"], "mode": "graph"},
    )
    assert session.status_code == 200
    return client, session.json()["session_id"]


def complete_six_nodes(client: TestClient, session_id: str):
    assert client.post(f"/api/sessions/{session_id}/graph/start").status_code == 200
    response = None
    for index in range(6):
        response = client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={
                "answer_text": f"回答 {index}",
                "client_submission_id": f"answer-{index}",
            },
        )
        assert response.status_code == 200
    return response


def count_answers(client: TestClient, session_id: str) -> int:
    with client.app.state.session_factory() as db:
        return db.scalar(
            select(func.count(AnswerAttempt.id)).where(AnswerAttempt.session_id == session_id)
        ) or 0


def test_completed_graph_resume_is_stable_and_does_not_add_answer(tmp_path):
    client, session_id = graph_client(tmp_path)
    completed = complete_six_nodes(client, session_id)
    assert completed.json()["status"] == "completed"
    before = count_answers(client, session_id)

    original_builder = client.app.state.interview_graph_builder

    class NoInvokeGraph:
        def __init__(self, graph):
            self.graph = graph

        def get_state(self, *args, **kwargs):
            return self.graph.get_state(*args, **kwargs)

        def invoke(self, *args, **kwargs):
            raise AssertionError("completed graph must not be invoked")

    def guard_builder(agents, checkpointer, db, *, event_sink=None):
        return NoInvokeGraph(
            original_builder(agents, checkpointer, db, event_sink=event_sink)
        )

    client.app.state.interview_graph_builder = guard_builder

    response = client.post(
        f"/api/sessions/{session_id}/graph/resume",
        json={"answer_text": "late answer", "client_submission_id": "late-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert count_answers(client, session_id) == before


def test_duplicate_graph_resume_returns_state_without_second_answer(tmp_path):
    client, session_id = graph_client(tmp_path)
    client.post(f"/api/sessions/{session_id}/graph/start")
    payload = {"answer_text": "同一回答", "client_submission_id": "same-1"}

    first = client.post(f"/api/sessions/{session_id}/graph/resume", json=payload)
    second = client.post(f"/api/sessions/{session_id}/graph/resume", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["current_question"] == first.json()["current_question"]
    assert count_answers(client, session_id) == 1
