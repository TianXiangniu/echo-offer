import hashlib
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.providers import (
    AssessmentProviderError,
    AssessmentResult,
    BatchAssessmentItem,
    FollowupDecision,
    RubricAssessmentResult,
    RuleBasedAssessmentProvider,
)
from app.main import create_app
from app.rubrics import build_rubric


class FakeAssessmentProvider:
    def __init__(
        self,
        failures_remaining: int = 0,
        invalid: bool = False,
        provider_error: AssessmentProviderError | None = None,
        followup_decisions: list[bool] | None = None,
    ):
        self.failures_remaining = failures_remaining
        self.invalid = invalid
        self.provider_error = provider_error
        self.followup_decisions = list(followup_decisions or [])
        self.calls = 0
        self.batch_calls = 0
        self.decide_calls = 0
        self.feedback_calls = 0

    def decide_followup(
        self,
        question_prompt,
        rubric_items,
        answer_text,
        prepared_followups,
        previous_followups=(),
        persona="standard",
    ):
        self.decide_calls += 1
        self.last_persona = persona
        if not self.followup_decisions:
            return FollowupDecision(should_followup=False)
        should = self.followup_decisions.pop(0)
        if not should:
            return FollowupDecision(should_followup=False)
        return FollowupDecision(
            should_followup=True,
            reason="probe",
            followup_question="你提到的方案在数据量更大时还成立吗？",
        )

    def feedback_for_answer(self, question_prompt, answer_text):
        self.feedback_calls += 1
        from app.providers import PracticeFeedback

        return PracticeFeedback(
            content="你把机制讲清楚了，但缺少具体场景。下次试着用一个真实案例说明。",
            focus_hints=("如果继续追问，可能会问你怎么度量效果",),
        )

    def assess(self, question, answer_text, status):
        self.calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            if self.provider_error is not None:
                raise self.provider_error
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

    def assess_batch(self, cases):
        self.batch_calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            if self.provider_error is not None:
                raise self.provider_error
            raise RuntimeError("fake provider failure")
        return tuple(
            BatchAssessmentItem(
                answer_id=case.answer_id,
                question_id=case.question_id,
                result=self.assess(case.question, case.answer_text, "submitted"),
            )
            for case in cases
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
def provider_error_ai_client(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'ai-provider-error-test.db'}"
    app = create_app(
        database_url,
        upload_root=tmp_path / "uploads",
        # 超时属瞬态错误会被自动重试：全部调用都失败才能确定性地测持久失败
        assessment_provider=FakeAssessmentProvider(
            failures_remaining=99,
            provider_error=AssessmentProviderError("provider_timeout", "模型请求超时"),
        ),
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
def provider_error_ai_session_context(provider_error_ai_client):
    return create_test_session(provider_error_ai_client)


@pytest.fixture
def invalid_ai_session_context(invalid_ai_client):
    return create_test_session(invalid_ai_client)


class FakeVerifyingProvider(FakeAssessmentProvider):
    """在 FakeAssessmentProvider 之上加复核：可编程每条观察的判定。"""

    def __init__(self, verdicts: dict[str, dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.verdicts = verdicts or {}
        self.verify_calls = 0

    def verify_batch(self, entries):
        self.verify_calls += 1
        return {
            entry["rubric_id"]: self.verdicts.get(
                entry["rubric_id"],
                {"quote_relevant": True, "level_supported": True, "suggested_level": None},
            )
            for entry in entries
        }
