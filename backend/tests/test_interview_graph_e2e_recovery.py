from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, Lock

import pytest
from sqlalchemy import func, select
from fastapi.testclient import TestClient

import app.interview_graph_api as graph_api
from app.interview_graph_types import EvidenceVerification, InterviewPlan, InterviewPlanNode, InterviewerTurn
from app.main import create_app
from app.models import AnswerAttempt, InterviewGraphSubmissionReceipt, utc_now
from app.providers import AssessmentProviderError
from app.schemas import GraphAnswerSubmission
from app.workflow_common import ConflictError


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


class NoNetworkAssessmentProvider:
    evaluator = "test-no-network"

    def assess_batch(self, cases):
        return ()


def graph_client(tmp_path, agents=None):
    app = create_app(
        f"sqlite:///{tmp_path / 'graph-e2e.db'}",
        upload_root=tmp_path / "uploads",
        assessment_provider=NoNetworkAssessmentProvider(),
    )
    app.state.interview_graph_agents = agents or StableGraphAgents()
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


def test_concurrent_graph_resume_does_not_invoke_graph_twice(tmp_path):
    client, session_id = graph_client(tmp_path)
    client.post(f"/api/sessions/{session_id}/graph/start")
    original_builder = client.app.state.interview_graph_builder
    first_entered = Event()
    release_first = Event()
    counter_lock = Lock()
    state = {"active": False, "invokes": 0}

    def guarded_builder(agents, checkpointer, db, *, event_sink=None):
        graph = original_builder(agents, checkpointer, db, event_sink=event_sink)

        class GuardedGraph:
            def get_state(self, *args, **kwargs):
                return graph.get_state(*args, **kwargs)

            def invoke(self, *args, **kwargs):
                if state["active"]:
                    with counter_lock:
                        state["invokes"] += 1
                        first = state["invokes"] == 1
                    if first:
                        first_entered.set()
                        assert release_first.wait(5)
                return graph.invoke(*args, **kwargs)

        return GuardedGraph()

    client.app.state.interview_graph_builder = guarded_builder
    state["active"] = True

    def submit(index: int):
        with client.app.state.session_factory() as db:
            return graph_api.resume_graph(
                db,
                session_id,
                GraphAnswerSubmission(
                    answer_text="并发回答",
                    client_submission_id="same-concurrent",
                ),
                graph_builder=client.app.state.interview_graph_builder,
                agents=client.app.state.interview_graph_agents,
                checkpointer=client.app.state.interview_graph_checkpointer,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, 0)
        assert first_entered.wait(2)
        second = pool.submit(submit, 1)
        release_first.set()
        first_result = first.result()
        second_result = second.result()

    assert first_result["status"] == "awaiting_answer"
    assert second_result["status"] == "awaiting_answer"
    assert state["invokes"] == 1
    assert count_answers(client, session_id) == 1


def test_failed_graph_submission_cannot_retry_after_invoke(tmp_path):
    client, session_id = graph_client(tmp_path)
    client.post(f"/api/sessions/{session_id}/graph/start")
    original_builder = client.app.state.interview_graph_builder
    invokes = {"count": 0}

    def failing_builder(agents, checkpointer, db, *, event_sink=None):
        graph = original_builder(agents, checkpointer, db, event_sink=event_sink)

        class FailingGraph:
            def get_state(self, *args, **kwargs):
                return graph.get_state(*args, **kwargs)

            def invoke(self, *args, **kwargs):
                invokes["count"] += 1
                raise RuntimeError("model failed after reservation")

        return FailingGraph()

    client.app.state.interview_graph_builder = failing_builder
    payload = GraphAnswerSubmission(
        answer_text="会触发模型失败",
        client_submission_id="failed-submission",
    )
    with client.app.state.session_factory() as db:
        with pytest.raises(RuntimeError, match="model failed"):
            graph_api.resume_graph(
                db,
                session_id,
                payload,
                graph_builder=client.app.state.interview_graph_builder,
                agents=client.app.state.interview_graph_agents,
                checkpointer=client.app.state.interview_graph_checkpointer,
            )

    with client.app.state.session_factory() as db:
        receipt = db.scalar(
            select(InterviewGraphSubmissionReceipt).where(
                InterviewGraphSubmissionReceipt.session_id == session_id,
                InterviewGraphSubmissionReceipt.client_submission_id == "failed-submission",
            )
        )
        assert receipt is not None
        assert receipt.status == "failed"

    with client.app.state.session_factory() as db:
        with pytest.raises(ConflictError, match="processing or has failed"):
            graph_api.resume_graph(
                db,
                session_id,
                payload,
                graph_builder=client.app.state.interview_graph_builder,
                agents=client.app.state.interview_graph_agents,
                checkpointer=client.app.state.interview_graph_checkpointer,
            )
    assert invokes["count"] == 1


def test_submission_reservation_is_unique_across_database_sessions(tmp_path):
    client, session_id = graph_client(tmp_path)
    payload = GraphAnswerSubmission(
        answer_text="数据库竞争回答",
        client_submission_id="database-race",
    )

    def reserve(_index: int):
        with client.app.state.session_factory() as db:
            try:
                return graph_api._reserve_submission(db, session_id, payload)
            except Exception as error:
                return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in (pool.submit(reserve, 0), pool.submit(reserve, 1))]

    assert results.count(True) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1


def test_stale_submission_reservation_is_cleaned_as_failed(tmp_path):
    client, session_id = graph_client(tmp_path)
    payload = GraphAnswerSubmission(
        answer_text="过期收据回答",
        client_submission_id="stale-submission",
    )
    with client.app.state.session_factory() as db:
        db.add(
            InterviewGraphSubmissionReceipt(
                id="stale-receipt",
                session_id=session_id,
                client_submission_id=payload.client_submission_id,
                answer_text_hash=graph_api._submission_hash(payload.answer_text),
                status="processing",
                created_at=utc_now() - timedelta(hours=3),
            )
        )
        db.commit()

    with client.app.state.session_factory() as db:
        with pytest.raises(ConflictError, match="expired"):
            graph_api._reserve_submission(db, session_id, payload)

    with client.app.state.session_factory() as db:
        receipt = db.get(InterviewGraphSubmissionReceipt, "stale-receipt")
        assert receipt is not None
        assert receipt.status == "failed"


def test_completed_resume_is_read_only_after_projection_failure(tmp_path, monkeypatch):
    client, session_id = graph_client(tmp_path)
    client.post(f"/api/sessions/{session_id}/graph/start")
    for index in range(5):
        response = client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={
                "answer_text": f"回答 {index}",
                "client_submission_id": f"answer-{index}",
            },
        )
        assert response.status_code == 200

    original = graph_api.project_graph_event

    def fail_candidate(db, event, *, commit=True):
        if event["event_kind"] == "candidate_answer":
            raise RuntimeError("projection unavailable")
        return original(db, event, commit=commit)

    monkeypatch.setattr(graph_api, "project_graph_event", fail_candidate)
    with pytest.raises(RuntimeError, match="projection unavailable"):
        client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={"answer_text": "回答 5", "client_submission_id": "answer-5"},
        )
    monkeypatch.setattr(graph_api, "project_graph_event", original)

    before = count_answers(client, session_id)
    response = client.post(
        f"/api/sessions/{session_id}/graph/resume",
        json={"answer_text": "late answer", "client_submission_id": "late-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["assessment"]["status"] == "pending"
    assert count_answers(client, session_id) == before == 5


class ProviderUnavailableGraphAgents:
    def _error(self):
        raise AssessmentProviderError("provider_not_configured", "模型服务尚未配置")

    def plan(self, state):
        self._error()

    def ask(self, state):
        self._error()

    def verify(self, state):
        self._error()


def test_provider_unavailable_api_returns_safe_degraded_state(tmp_path):
    client, session_id = graph_client(tmp_path, ProviderUnavailableGraphAgents())

    started = client.post(f"/api/sessions/{session_id}/graph/start")
    assert started.status_code == 200
    assert started.json()["status"] == "awaiting_answer"
    assert started.json()["degraded"] is True

    events = client.get(f"/api/sessions/{session_id}/graph/events")
    assert events.status_code == 200
    assert "provider_not_configured" not in events.text
    assert "question_ready" in events.text
