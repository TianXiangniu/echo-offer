"""对话式面试全流程测试（fake provider）。"""

import json

from app.models import InterviewQuestion
from tests.conftest import FakeAssessmentProvider, create_test_session
from tests.test_assessment_batch import _make_verifying_client  # noqa: F401 (确保导入路径有效)


class FakeDialogProvider(FakeAssessmentProvider):
    """可编程的面试官：按队列返回下一句，队列耗尽后按饱和度收束。"""

    def __init__(self, questions_queue=None, saturate_after=3, **kwargs):
        super().__init__(**kwargs)
        self.queue = list(questions_queue or [])
        self.saturate_after = saturate_after
        self.interviewer_calls = 0

    def generate_interviewer_turn(self, payload):
        self.interviewer_calls += 1
        if self.queue:
            item = self.queue.pop(0)
            return {
                "question": item["question"],
                "saturated": item.get("saturated", False),
            }
        return {
            "question": f"追问第 {payload['rounds_used'] + 1} 轮：具体展开了说说？",
            "saturated": payload["rounds_used"] >= self.saturate_after,
        }


def _make_dialog_client(tmp_path, **kwargs):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(
        f"sqlite:///{tmp_path / 'dialog.db'}",
        upload_root=tmp_path / "uploads",
        assessment_provider=FakeDialogProvider(**kwargs),
    )
    return TestClient(app)


def _submit_answer(client, session_id, question):
    return client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": question["id"],
            "client_submission_id": f"k-{question['id'][:8]}",
            "status": "submitted",
            "answer_text": "这题我从机制、边界和取舍三个角度回答。",
        },
    )


def test_dialog_full_three_stage_flow(tmp_path):
    with _make_dialog_client(tmp_path) as client:
        profile = client.post(
            "/api/profile",
            json={
                "resume_text": "简历内容",
                "project": {
                    "project_name": "知识库 Agent",
                    "background_goal": "降本",
                    "tech_stack": "Python",
                    "responsibilities": "RAG 链路",
                    "core_solution": "混合检索",
                    "engineering_challenges": "延迟",
                    "failure_improvements": "评估集",
                    "quantified_results": "命中率 +18%",
                },
            },
        ).json()
        session = client.post(
            "/api/sessions",
            json={"profile_id": profile["profile_id"], "mode": "dialog"},
        ).json()
        session_id = session["session_id"]
        assert len(session["questions"]) == 5  # 知识题 5 道（对话替代项目题）

        view = client.get(f"/api/sessions/{session_id}").json()
        assert view["stage"] == "intro"
        assert view["timeline"][0]["role"] == "interviewer"
        assert "自我介绍" in view["timeline"][0]["content"]

        # 自我介绍 → 进入深挖
        result = client.post(
            f"/api/sessions/{session_id}/dialog/answer",
            json={"text": "我是张伟，两年 Agent 经验，做过企业知识库问答系统。"},
        ).json()
        assert result["stage"] == "project_dialog"

        # 持续回答直到深挖收束（默认第 4 轮饱和）
        for _ in range(10):
            view = client.get(f"/api/sessions/{session_id}").json()
            if view["stage"] != "project_dialog":
                break
            client.post(
                f"/api/sessions/{session_id}/dialog/answer",
                json={"text": "这轮我讲了具体方案和量化结果。"},
            )
        assert view["stage"] == "knowledge"

        # 深挖合并为 deep_dive 题（order 0），回答文本包含全部对话
        with client.app.state.session_factory() as db:
            from sqlalchemy import select

            from app.models import AnswerAttempt

            deep_question = db.scalars(
                select(InterviewQuestion).where(
                    InterviewQuestion.session_id == session_id,
                    InterviewQuestion.order == 0,
                )
            ).first()
            assert deep_question is not None
            assert deep_question.knowledge_point_id == "project.deep_dive"
            answer = db.scalars(
                select(AnswerAttempt).where(
                    AnswerAttempt.question_id == deep_question.id
                )
            ).first()
            assert "面试官：" in answer.answer_text
            assert "候选人：" in answer.answer_text
            assert "张伟" in answer.answer_text

        # 知识题 5 道
        for question in view["questions"]:
            _submit_answer(client, session_id, question)
        view = client.get(f"/api/sessions/{session_id}").json()
        assert view["stage"] == "wrap_up"
        assert any("想问我的吗" in item["content"] for item in view["timeline"] if item["role"] == "interviewer")

        # 反问 → 完成 → 评分
        client.post(
            f"/api/sessions/{session_id}/dialog/answer",
            json={"text": "我想问团队对评估体系的投入程度。"},
        )
        view = client.get(f"/api/sessions/{session_id}").json()
        assert view["stage"] == "completed"
        assessment = client.post(f"/api/sessions/{session_id}/assessment")
        assert assessment.status_code == 200
        assert assessment.json()["job_status"] == "succeeded"
        report = client.get(f"/api/sessions/{session_id}/report").json()
        assert report["score_100"] is not None
        # transcript 包含深挖题（order 0）与知识题
        assert any(item["order"] == 0 for item in report["transcript"])


def test_dialog_round_budget_and_early_finish(tmp_path):
    with _make_dialog_client(
        tmp_path,
        questions_queue=[
            {"question": f"第 {i} 轮追问", "saturated": False} for i in range(1, 12)
        ],
    ) as client:
        profile = client.post(
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
        ).json()
        session_id = client.post(
            "/api/sessions",
            json={"profile_id": profile["profile_id"], "mode": "dialog"},
        ).json()["session_id"]

        client.post(
            f"/api/sessions/{session_id}/dialog/answer",
            json={"text": "自我介绍内容"},
        )
        # 一直答到上限
        for _ in range(15):
            view = client.get(f"/api/sessions/{session_id}").json()
            if view["stage"] != "project_dialog":
                break
            client.post(
                f"/api/sessions/{session_id}/dialog/answer",
                json={"text": "继续回答内容"},
            )
        assert view["stage"] == "knowledge"

    # 提前结束：新会话走 dialog/finish
    with _make_dialog_client(tmp_path) as client:
        profile = client.post(
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
        ).json()
        session_id = client.post(
            "/api/sessions",
            json={"profile_id": profile["profile_id"], "mode": "dialog"},
        ).json()["session_id"]
        client.post(
            f"/api/sessions/{session_id}/dialog/answer",
            json={"text": "自我介绍"},
        )
        finished = client.post(f"/api/sessions/{session_id}/dialog/finish")
        assert finished.json()["stage"] == "knowledge"


def test_classic_mode_unchanged(client):
    """经典模式回归：仍是 8 题、无对话时间线。"""
    session = client.post(
        "/api/sessions",
        json={
            "profile_id": _make_profile(client),
        },
    ).json()
    assert len(session["questions"]) == 8
    view = client.get(f"/api/sessions/{session['session_id']}").json()
    assert view["mode"] == "classic"
    assert view["stage"] == "knowledge"
    assert view["timeline"] == []


def _make_profile(client):
    response = client.post(
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
    return response.json()["profile_id"]
