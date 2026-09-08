from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.interview_graph_types import EvidenceVerification, InterviewPlan, InterviewPlanNode, InterviewerTurn
from app.llm_observability import ModelCallRecord, ModelPrice, emit_model_call
from app.main import create_app
from app.models import AssessmentRun, InterviewReport, LlmCallTrace
from app.providers import AssessmentResult, BatchAssessmentItem, RubricAssessmentResult
from app.rubrics import build_rubric


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


class TracingGraphAgents(StableGraphAgents):
    def _trace(self, call_kind: str) -> None:
        emit_model_call(
            ModelCallRecord.success(
                trace_id="",
                call_kind=call_kind,
                provider="test",
                model_name="graph-test-model",
                prompt_version="graph-test-v1",
                input_tokens=100,
                output_tokens=50,
                latency_ms=10,
                request_bytes=20,
                response_bytes=30,
            )
        )

    def plan(self, state):
        self._trace("planner")
        return super().plan(state)

    def ask(self, state):
        self._trace("interviewer")
        return super().ask(state)

    def verify(self, state):
        self._trace("evidence_verifier")
        return super().verify(state)


class LocalAssessmentProvider:
    evaluator = "local-graph-test-v1"
    prompt_version = "graph-test-v1"

    def __init__(self):
        self.batch_calls = 0

    def assess_batch(self, cases):
        self.batch_calls += 1
        items = []
        for case in cases:
            answer_hash = hashlib.sha256(case.answer_text.encode("utf-8")).hexdigest()
            rubric_items = tuple(
                RubricAssessmentResult(
                    rubric_id=item.rubric_id,
                    level=3,
                    evidence_start=0,
                    evidence_end=len(case.answer_text),
                    quoted_text=case.answer_text,
                    answer_text_hash=answer_hash,
                    confidence=0.9,
                )
                for item in build_rubric(case.question).items
            )
            items.append(
                BatchAssessmentItem(
                    answer_id=case.answer_id,
                    question_id=case.question_id,
                    result=AssessmentResult(
                        level=3,
                        evidence_start=0,
                        evidence_end=len(case.answer_text),
                        quoted_text=case.answer_text,
                        answer_text_hash=answer_hash,
                        gaps=(),
                        confidence=0.9,
                        rubric_items=rubric_items,
                        evaluator=self.evaluator,
                    ),
                )
            )
        return tuple(items)


def _graph_app(tmp_path, *, agents, assessment_provider=None):
    app = create_app(
        f"sqlite:///{tmp_path / 'graph-scoring.db'}",
        upload_root=tmp_path / "uploads",
        assessment_provider=assessment_provider,
    )
    app.state.interview_graph_agents = agents
    return app


def _create_session(client: TestClient) -> str:
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
    return session.json()["session_id"]


def test_completed_graph_resume_returns_assessment(tmp_path):
    provider = LocalAssessmentProvider()
    app = _graph_app(tmp_path, agents=StableGraphAgents(), assessment_provider=provider)
    with TestClient(app) as client:
        session_id = _create_session(client)
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

        assert response.json()["status"] == "completed"
        assert response.json()["assessment"]["status"] == "valid"
        assert response.json()["assessment"]["evaluated_count"] == 6
        assert provider.batch_calls == 2

        with app.state.session_factory() as db:
            assert db.scalar(select(func.count(AssessmentRun.id))) == 6
            assert db.scalar(
                select(InterviewReport.id).where(InterviewReport.session_id == session_id)
            ) is not None

        repeated = client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={"answer_text": "late answer", "client_submission_id": "late-1"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["assessment"]["status"] == "valid"
        assert provider.batch_calls == 2


def test_graph_model_calls_are_observed(tmp_path):
    app = _graph_app(tmp_path, agents=TracingGraphAgents())
    app.state.model_settings = replace(
        app.state.model_settings,
        pricing=(ModelPrice("graph-test-model", Decimal("1"), Decimal("2")),),
    )
    with TestClient(app) as client:
        session_id = _create_session(client)
        assert client.post(f"/api/sessions/{session_id}/graph/start").status_code == 200
        assert client.post(
            f"/api/sessions/{session_id}/graph/resume",
            json={"answer_text": "回答", "client_submission_id": "answer-1"},
        ).status_code == 200

        with app.state.session_factory() as db:
            rows = list(
                db.scalars(
                    select(LlmCallTrace).where(LlmCallTrace.session_id == session_id)
                )
            )
        assert {row.call_kind for row in rows} >= {
            "planner",
            "interviewer",
            "evidence_verifier",
        }
        assert all(row.cost_cny is not None for row in rows)

        summary = client.get(f"/api/observability/summary?session_id={session_id}")
        assert summary.status_code == 200
        assert Decimal(summary.json()["known_cost_cny"]) > 0
