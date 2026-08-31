import hashlib
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.providers import AssessmentResult, RubricAssessmentResult, RuleBasedAssessmentProvider
from app.main import create_app
from app.rubrics import build_rubric


class FakeAssessmentProvider:
    def __init__(self, failures_remaining: int = 0, invalid: bool = False):
        self.failures_remaining = failures_remaining
        self.invalid = invalid
        self.calls = 0

    def assess(self, question, answer_text, status):
        self.calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("fake provider failure")

        answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
        items = tuple(
            replace(
                RubricAssessmentResult(
                    rubric_id=item.rubric_id,
                    level=level,
                    evidence_start=0,
                    evidence_end=len(answer_text),
                    quoted_text=answer_text,
                    answer_text_hash=answer_hash,
                    confidence=0.8,
                ),
                validity="invalid" if self.invalid and item.rubric_id == "mechanism" else "valid",
                invalid_reason="证据无法验证" if self.invalid and item.rubric_id == "mechanism" else None,
            )
            for item, level in zip(build_rubric(question).items, (3, 2, 3, 4), strict=True)
        )
        return AssessmentResult(
            level=3,
            evidence_start=0,
            evidence_end=len(answer_text),
            quoted_text=answer_text,
            answer_text_hash=answer_hash,
            gaps=("mechanism",),
            confidence=0.8,
            rubric_items=items,
            evaluator="fake-blind-rubric-v1",
        )


@pytest.fixture
def client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    app = create_app(
        database_url,
        upload_root=tmp_path / "uploads",
        assessment_provider=RuleBasedAssessmentProvider(),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ai_client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'ai-test.db'}"
    app = create_app(
        database_url,
        upload_root=tmp_path / "uploads",
        assessment_provider=FakeAssessmentProvider(),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def failing_ai_client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'ai-failure-test.db'}"
    app = create_app(
        database_url,
        upload_root=tmp_path / "uploads",
        assessment_provider=FakeAssessmentProvider(failures_remaining=1),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def invalid_ai_client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'ai-invalid-test.db'}"
    app = create_app(
        database_url,
        upload_root=tmp_path / "uploads",
        assessment_provider=FakeAssessmentProvider(invalid=True),
    )
    with TestClient(app) as test_client:
        yield test_client


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
    profile_id = profile_response.json()["profile_id"]
    session_response = client.post("/api/sessions", json={"profile_id": profile_id})
    assert session_response.status_code == 200
    session = session_response.json()
    return session["session_id"], session["questions"]


@pytest.fixture
def session_context(client):
    return create_test_session(client)


@pytest.fixture
def ai_session_context(ai_client):
    return create_test_session(ai_client)


@pytest.fixture
def failing_ai_session_context(failing_ai_client):
    return create_test_session(failing_ai_client)


@pytest.fixture
def invalid_ai_session_context(invalid_ai_client):
    return create_test_session(invalid_ai_client)
