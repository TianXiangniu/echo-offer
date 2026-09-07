import hashlib
import json

import pytest

from app.assessment_engine import AssessmentResponseError, parse_model_assessment
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import FollowupDecision
from app.rubrics import build_rubric
from tests.conftest import FakeAssessmentProvider

from sqlalchemy import select

from app.models import (
    AnswerAttempt,
    InterviewFollowup,
    InterviewQuestion,
    InterviewSession,
)


FOLLOWUP_PROMPT = "你提到的方案在数据量更大时还成立吗？"


def make_client(tmp_path, followup_decisions):
    app = create_app(
        f"sqlite:///{tmp_path / 'followup.db'}",
        upload_root=tmp_path / "uploads",
        assessment_provider=FakeAssessmentProvider(
            followup_decisions=list(followup_decisions)
        ),
    )
    return TestClient(app)


def create_session_and_answer_first(client, answer_text="我说明了机制、边界和工程取舍。"):
    profile_response = client.post(
        "/api/profile",
        json={
            "resume_text": "我做过一个面向企业知识库的 RAG Agent 项目。",
            "project": {
                "project_name": "企业知识库问答 Agent",
                "background_goal": "降低内部知识检索成本",
                "tech_stack": "Python、FastAPI",
                "responsibilities": "负责检索链路",
                "core_solution": "查询改写和混合检索",
                "engineering_challenges": "召回质量",
                "failure_improvements": "增加评估集",
                "quantified_results": "命中率提升 18%",
            },
        },
    )
    assert profile_response.status_code == 200
    session = client.post(
        "/api/sessions", json={"profile_id": profile_response.json()["profile_id"]}
    ).json()
    session_id = session["session_id"]
    questions = session["questions"]
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "primary-1",
            "status": "submitted",
            "answer_text": answer_text,
        },
    )
    assert response.status_code == 200
    return session_id, questions


def test_decide_creates_followup_and_consumes_budget(tmp_path):
    with make_client(tmp_path, [True]) as client:
        session_id, questions = create_session_and_answer_first(client)

        first = client.post(
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/decide"
        )
        assert first.status_code == 200
        followup = first.json()["followup"]
        assert followup["status"] == "pending"
        assert followup["question_text"] == FOLLOWUP_PROMPT

        # 幂等：重复 decide 返回同一追问，不再调用模型
        second = client.post(
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/decide"
        )
        assert second.status_code == 200
        assert second.json()["followup"]["id"] == followup["id"]

        session_view = client.get(f"/api/sessions/{session_id}").json()
        assert session_view["questions"][0]["followup"]["status"] == "pending"


def test_decide_waives_when_budget_exhausted(tmp_path):
    with make_client(tmp_path, [True] * 6) as client:
        profile_response = client.post(
            "/api/profile",
            json={
                "resume_text": "简历",
                "project": {
                    "project_name": "P",
                    "background_goal": "g",
                    "tech_stack": "t",
                    "responsibilities": "r",
                    "core_solution": "c",
                    "engineering_challenges": "e",
                    "failure_improvements": "f",
                    "quantified_results": "q",
                },
            },
        )
        session_id = client.post(
            "/api/sessions", json={"profile_id": profile_response.json()["profile_id"]}
        ).json()["session_id"]
        questions = client.get(f"/api/sessions/{session_id}").json()["questions"]

        # 前 4 道题各消费一次预算
        for question in questions[:4]:
            client.post(
                f"/api/sessions/{session_id}/answers",
                json={
                    "question_id": question["id"],
                    "client_submission_id": f"a-{question['id'][:8]}",
                    "status": "submitted",
                    "answer_text": "回答内容",
                },
            )
            decide = client.post(
                f"/api/sessions/{session_id}/questions/{question['id']}/followup/decide"
            )
            assert decide.json()["followup"]["status"] == "pending"

        # 第 5 题：预算耗尽，直接 waived，不调用模型
        fifth = questions[4]
        client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "question_id": fifth["id"],
                "client_submission_id": "a-fifth",
                "status": "submitted",
                "answer_text": "回答内容",
            },
        )
        decide = client.post(
            f"/api/sessions/{session_id}/questions/{fifth['id']}/followup/decide"
        )
        assert decide.status_code == 200
        assert decide.json()["followup"] is None
        with client.app.state.session_factory() as db:
            from app.models import InterviewFollowup as IF

            waived = db.scalar(
                select(IF).where(IF.question_id == fifth["id"], IF.status == "waived")
            )
            assert waived is not None

        with client.app.state.session_factory() as db:
            session = db.get(InterviewSession, session_id)
            assert session.followup_budget_used == 4


def test_decide_without_primary_answer_waives_without_model_call(tmp_path):
    with make_client(tmp_path, []) as client:
        profile_response = client.post(
            "/api/profile",
            json={
                "resume_text": "简历",
                "project": {
                    "project_name": "P",
                    "background_goal": "g",
                    "tech_stack": "t",
                    "responsibilities": "r",
                    "core_solution": "c",
                    "engineering_challenges": "e",
                    "failure_improvements": "f",
                    "quantified_results": "q",
                },
            },
        )
        session_id = client.post(
            "/api/sessions", json={"profile_id": profile_response.json()["profile_id"]}
        ).json()["session_id"]
        questions = client.get(f"/api/sessions/{session_id}").json()["questions"]

        decide = client.post(
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/decide"
        )
        assert decide.status_code == 200
        assert decide.json()["followup"] is None


def test_followup_answer_round_trip_and_idempotency(tmp_path):
    with make_client(tmp_path, [True]) as client:
        session_id, questions = create_session_and_answer_first(client)
        decide = client.post(
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/decide"
        )
        assert decide.json()["followup"]["status"] == "pending"

        answer_url = (
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/answer"
        )
        payload = {
            "client_submission_id": "fu-1",
            "answer_text": "数据量更大时先分桶验证，再做索引侧调优。",
        }
        submitted = client.post(answer_url, json=payload)
        assert submitted.status_code == 200
        followup = submitted.json()["followup"]
        assert followup["status"] == "answered"
        assert followup["answer_text"] == payload["answer_text"]

        # 相同提交幂等返回
        again = client.post(answer_url, json=payload)
        assert again.status_code == 200
        assert again.json()["followup"]["id"] == followup["id"]

        # 不同内容的重复提交冲突
        conflict = client.post(
            answer_url,
            json={
                "client_submission_id": "fu-1",
                "answer_text": "另一种说法",
            },
        )
        assert conflict.status_code == 409

        # 全新提交 id 也不可修改
        conflict_two = client.post(
            answer_url,
            json={
                "client_submission_id": "fu-2",
                "answer_text": "再答一次",
            },
        )
        assert conflict_two.status_code == 409

        with client.app.state.session_factory() as db:
            stored = db.scalar(
                select(InterviewFollowup).where(
                    InterviewFollowup.question_id == questions[0]["id"]
                )
            )
            assert stored.status == "answered"
            assert stored.answer_text_hash == hashlib.sha256(
                payload["answer_text"].encode("utf-8")
            ).hexdigest()


def test_followup_participates_in_batch_assessment(tmp_path):
    with make_client(tmp_path, [True]) as client:
        session_id, questions = create_session_and_answer_first(client)
        client.post(f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/decide")
        client.post(
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/answer",
            json={
                "client_submission_id": "fu-1",
                "answer_text": "数据量更大时先分桶验证，再做索引侧重构。",
            },
        )
        # 提交剩余题目
        for index, question in enumerate(questions[1:], start=2):
            response = client.post(
                f"/api/sessions/{session_id}/answers",
                json={
                    "question_id": question["id"],
                    "client_submission_id": f"bulk-{index}",
                    "status": "submitted",
                    "answer_text": f"第 {index} 题回答：机制、边界与取舍。",
                },
            )
            assert response.status_code == 200

        assessment = client.post(f"/api/sessions/{session_id}/assessment")
        assert assessment.status_code == 200
        assert assessment.json()["job_status"] == "succeeded"

        report = client.get(f"/api/sessions/{session_id}/report")
        assert report.status_code == 200
        assert report.json()["score_100"] is not None


def test_parse_model_assessment_accepts_followup_evidence():
    question = build_question_specs_single()
    rubric = build_rubric(question)
    answer_text = "首答内容。"
    followup_text = "追问补充：先分桶再定位。"
    content = json.dumps(
        {
            "items": [
                {
                    "rubric_id": "correctness",
                    "level": 3,
                    "quoted_text": "先分桶再定位。",
                    "confidence": 0.8,
                },
                {
                    "rubric_id": "mechanism",
                    "level": 2,
                    "quoted_text": "首答内容。",
                    "confidence": 0.7,
                },
                {
                    "rubric_id": "scenario",
                    "level": 2,
                    "quoted_text": "首答内容。",
                    "confidence": 0.7,
                },
                {
                    "rubric_id": "engineering",
                    "level": 3,
                    "quoted_text": "首答内容。",
                    "confidence": 0.7,
                },
            ]
        },
        ensure_ascii=False,
    )

    items = parse_model_assessment(content, rubric, answer_text, followup_text)

    by_id = {item.rubric_id: item for item in items}
    assert by_id["correctness"].answer_text_hash == hashlib.sha256(
        followup_text.encode("utf-8")
    ).hexdigest()
    assert by_id["mechanism"].answer_text_hash == hashlib.sha256(
        answer_text.encode("utf-8")
    ).hexdigest()


def test_parse_model_assessment_rejects_quote_missing_from_both_texts():
    question = build_question_specs_single()
    rubric = build_rubric(question)
    content = json.dumps(
        {
            "items": [
                {
                    "rubric_id": rubric_id,
                    "level": 3,
                    "quoted_text": "不存在于任何文本的引用",
                    "confidence": 0.8,
                }
                for rubric_id in ("correctness", "mechanism", "scenario", "engineering")
            ]
        },
        ensure_ascii=False,
    )

    items = parse_model_assessment(content, rubric, "首答内容。", "追问内容。")

    assert all(item.validity == "invalid" for item in items)
    assert all(item.invalid_reason for item in items)


def build_question_specs_single():
    from app.question_bank import build_question_specs

    return build_question_specs()[3]


def test_feedback_generated_once_and_never_enters_scoring(tmp_path):
    with make_client(tmp_path, []) as client:
        session_id, questions = create_session_and_answer_first(client)
        question_id = questions[0]["id"]

        first = client.post(f"/api/sessions/{session_id}/questions/{question_id}/feedback")
        assert first.status_code == 200
        feedback = first.json()["feedback"]
        assert "缺少具体场景" in feedback["content"]
        assert feedback["focus_hints"]

        # 幂等：第二次调用不重复生成
        second = client.post(f"/api/sessions/{session_id}/questions/{question_id}/feedback")
        assert second.status_code == 200
        assert second.json()["feedback"]["content"] == feedback["content"]

        with client.app.state.session_factory() as db:
            provider = client.app.state.assessment_provider
            assert provider.feedback_calls == 1

        # 评分照常工作，且评分 case 组装不包含反馈内容
        for index, question in enumerate(questions[1:], start=2):
            client.post(
                f"/api/sessions/{session_id}/answers",
                json={
                    "question_id": question["id"],
                    "client_submission_id": f"fb-{index}",
                    "status": "submitted",
                    "answer_text": f"第 {index} 题回答。",
                },
            )
        assessment = client.post(f"/api/sessions/{session_id}/assessment")
        assert assessment.status_code == 200
        assert assessment.json()["job_status"] == "succeeded"


def test_feedback_requires_submitted_primary_answer(tmp_path):
    with make_client(tmp_path, []) as client:
        profile_response = client.post(
            "/api/profile",
            json={
                "resume_text": "简历",
                "project": {
                    "project_name": "P",
                    "background_goal": "g",
                    "tech_stack": "t",
                    "responsibilities": "r",
                    "core_solution": "c",
                    "engineering_challenges": "e",
                    "failure_improvements": "f",
                    "quantified_results": "q",
                },
            },
        )
        session_id = client.post(
            "/api/sessions", json={"profile_id": profile_response.json()["profile_id"]}
        ).json()["session_id"]
        questions = client.get(f"/api/sessions/{session_id}").json()["questions"]
        client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "question_id": questions[0]["id"],
                "client_submission_id": "skip-1",
                "status": "skipped",
                "answer_text": "",
            },
        )

        response = client.post(
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/feedback"
        )
        assert response.status_code == 409


def test_switches_off_skip_model_calls(tmp_path):
    from dataclasses import replace as dc_replace

    with make_client(tmp_path, []) as client:
        session_id, questions = create_session_and_answer_first(client)
        question_id = questions[0]["id"]

        client.app.state.model_settings = dc_replace(
            client.app.state.model_settings,
            followup_enabled=False,
            practice_feedback_enabled=False,
        )

        decide = client.post(
            f"/api/sessions/{session_id}/questions/{question_id}/followup/decide"
        )
        assert decide.status_code == 200
        assert decide.json()["followup"] is None
        feedback = client.post(
            f"/api/sessions/{session_id}/questions/{question_id}/feedback"
        )
        assert feedback.status_code == 200
        assert feedback.json()["feedback"] is None

        provider = client.app.state.assessment_provider
        assert provider.decide_calls == 0
        assert provider.feedback_calls == 0


def test_followup_chain_two_rounds_share_budget(tmp_path):
    with make_client(tmp_path, [True, True]) as client:
        session_id, questions = create_session_and_answer_first(client)
        qid = questions[0]["id"]
        decide_url = f"/api/sessions/{session_id}/questions/{qid}/followup/decide"
        answer_url = f"/api/sessions/{session_id}/questions/{qid}/followup/answer"

        first = client.post(decide_url).json()["followup"]
        assert first["status"] == "pending"
        client.post(answer_url, json={"client_submission_id": "r1", "answer_text": "第一轮回答"})

        second = client.post(decide_url).json()["followup"]
        assert second["status"] == "pending"
        with client.app.state.session_factory() as db:
            from app.models import InterviewFollowup as IF

            stored = db.scalar(select(IF).where(IF.question_id == qid, IF.status == "pending"))
            assert stored.round == 2
            session = db.get(InterviewSession, session_id)
            assert session.followup_budget_used == 2

        client.post(answer_url, json={"client_submission_id": "r2", "answer_text": "第二轮回答"})
        # 决策器说不用再挖 → 返回 null（链收束）
        third = client.post(decide_url).json()
        assert third["followup"] is None


def test_persona_flows_to_followup_provider(tmp_path):
    from dataclasses import replace as dc_replace

    with make_client(tmp_path, [True]) as client:
        client.app.state.model_settings = dc_replace(
            client.app.state.model_settings, persona="pressure"
        )
        session_id, questions = create_session_and_answer_first(client)
        client.post(f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/decide")
        provider = client.app.state.assessment_provider
        assert getattr(provider, "last_persona", "standard") == "pressure"


def test_persona_changes_decision_system_prompt():
    from app.providers import build_followup_decision_prompt

    gentle, _ = build_followup_decision_prompt("题", [], "回答", [], persona="gentle")
    pressure, _ = build_followup_decision_prompt("题", [], "回答", [], persona="pressure")
    assert "友好" in gentle and "压力" not in gentle
    assert "咄咄逼人" in pressure
    assert gentle != pressure


def test_current_question_includes_followup_state(tmp_path):
    with make_client(tmp_path, [True]) as client:
        session_id, questions = create_session_and_answer_first(client)
        decide = client.post(
            f"/api/sessions/{session_id}/questions/{questions[0]['id']}/followup/decide"
        )
        assert decide.json()["followup"]["status"] == "pending"

        view = client.get(f"/api/sessions/{session_id}").json()
        # 面试页从 current_question 渲染追问卡，字段缺失会导致追问永远不可见
        assert view["current_question"]["followup"]["status"] == "pending"


def test_answered_followup_visible_after_chain_waived(tmp_path):
    with make_client(tmp_path, [True]) as client:
        session_id, questions = create_session_and_answer_first(client)
        qid = questions[0]["id"]
        client.post(f"/api/sessions/{session_id}/questions/{qid}/followup/decide")
        client.post(
            f"/api/sessions/{session_id}/questions/{qid}/followup/answer",
            json={"client_submission_id": "r1", "answer_text": "第一轮回答内容"},
        )
        # 链收束（决策器说不再挖）后，已答追问在会话视图仍应可见
        view = client.get(f"/api/sessions/{session_id}").json()
        followup = view["questions"][0]["followup"]
        assert followup is not None
        assert followup["status"] == "answered"
        assert followup["answer_text"] == "第一轮回答内容"
