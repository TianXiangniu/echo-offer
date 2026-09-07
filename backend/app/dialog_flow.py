"""对话式面试状态机：intro → 项目深挖（动态收束）→ knowledge → wrap_up。

- 消息流逐条存 project_dialogs；深挖结束后合并文本落一道 project.deep_dive
  题目 + AnswerAttempt，完全复用现有评分/报告/画像机制。
- 面试中绝不评分；收束由面试官的饱和度判断驱动，程序只做上下限保护。
- 经典模式（classic）会话完全不经过本模块。
"""

from __future__ import annotations

import hashlib
import json
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AnswerAttempt,
    InterviewFollowup,
    InterviewQuestion,
    InterviewSession,
    ProjectDialog,
    ResumeProject,
    utc_now,
)
from .prompts import (
    DIALOG_MAX_ROUNDS,
    DIALOG_MIN_ROUNDS,
    FALLBACK_QUESTIONS,
    INTRO_MESSAGE,
    WRAPUP_MESSAGE,
)
from .feedback_flow import feedback_for_session
from .providers import AssessmentProviderError, FollowupDecisionProvider
from .question_bank import QuestionSpec
from .rubrics import (
    RubricItem,
    RubricSnapshot,
    build_rubric,
    rubric_to_dict,
)
from .workflow_common import (
    ConflictError,
    InvalidAnswerError,
    NotFoundError,
)

DEEP_DIVE_KNOWLEDGE_POINT = "project.deep_dive"
DEEP_DIVE_PROMPT = (
    "请介绍这个项目的整体情况：业务背景、你的职责、关键技术方案、"
    "遇到的困难和最终结果。结合面试中的对话一并评估。"
)


def _dialogs(db: Session, session_id: str) -> list[ProjectDialog]:
    rows = db.scalars(
        select(ProjectDialog)
        .where(ProjectDialog.session_id == session_id)
        .order_by(ProjectDialog.turn_no, ProjectDialog.role)
    )
    return list(rows)


def _rounds_used(db: Session, session_id: str) -> int:
    return sum(
        1
        for d in _dialogs(db, session_id)
        if d.role == "interviewer" and d.kind == "dialog"
    )


def _next_turn_no(db: Session, session_id: str) -> int:
    turns = list(
        db.scalars(
            select(ProjectDialog.turn_no).where(ProjectDialog.session_id == session_id)
        )
    )
    return (max(turns) if turns else 0) + 1


def _add_message(
    db: Session,
    session: InterviewSession,
    role: str,
    content: str,
    kind: str,
    heuristic_tag: str | None = None,
) -> ProjectDialog:
    message = ProjectDialog(
        id=str(uuid4()),
        session_id=session.id,
        turn_no=_next_turn_no(db, session.id),
        role=role,
        content=content,
        kind=kind,
        heuristic_tag=heuristic_tag,
    )
    db.add(message)
    db.commit()
    return message


def ensure_intro(db: Session, session: InterviewSession) -> None:
    """dialog 模式会话创建后调用：写开场白（幂等）。"""
    if _dialogs(db, session.id):
        return
    _add_message(db, session, "interviewer", INTRO_MESSAGE, "intro")


def _heuristic_tag(question: str) -> str | None:
    """报告复盘用的轻量标签：程序侧关键词规则，不进 prompt。"""
    if any(word in question for word in ("怎么测", "如何测", "基线", "口径", "怎么量化", "指标")):
        return "数字质疑"
    if any(word in question for word in ("为什么不用", "为什么没有", "备选", "换个")):
        return "备选方案"
    if any(word in question for word in ("10 倍", "涨", "高峰", "规模变大", "撑得住")):
        return "假设变化"
    if any(word in question for word in ("失效", "什么时候不行", "边界")):
        return "边界与失效"
    if any(word in question for word in ("你一个人", "分工", "谁负责", "团队")):
        return "分工边界"
    if any(word in question for word in ("重做", "重来", "改什么")):
        return "复盘改进"
    return "细节下钻"


def _project_reference_facts(db: Session, session: InterviewSession) -> tuple[str, ...]:
    """项目事实摘要作为深挖评分的参考要点。"""
    project = db.get(ResumeProject, session.resume_project_id)
    if project is None:
        return ()
    facts = []
    for value in (
        project.project_name,
        project.background_goal,
        project.responsibilities,
        project.core_solution,
        project.engineering_challenges,
        project.quantified_results,
    ):
        text = " ".join(str(value or "").split())
        if text:
            facts.append(text[:150])
    return tuple(facts)


def _finish_dialog(
    db: Session,
    session: InterviewSession,
    provider: FollowupDecisionProvider | None,
    closing_question: str | None = None,
) -> None:
    """收束深挖：落 deep_dive 题目与合并回答，生成衔接语，推进到 knowledge。"""
    if closing_question:
        _add_message(
            db, session, "interviewer", closing_question, "dialog", "收束"
        )

    dialogs = _dialogs(db, session.id)
    merged = "\n".join(
        f"{'面试官' if d.role == 'interviewer' else '候选人'}：{d.content}"
        for d in dialogs
        if d.content
    )
    reference_facts = _project_reference_facts(db, session)
    rubric = RubricSnapshot(
        version="dialog-v1",
        items=(
            RubricItem("correctness", "项目叙述是否真实自洽、概念是否正确", weight=1.0),
            RubricItem("mechanism", "是否讲清机制与原因；被追问后能否给出具体细节", weight=1.5),
            RubricItem("scenario", "是否结合具体场景、数据和实例", weight=1.0),
            RubricItem("engineering", "是否交代取舍、代价、边界与可执行方案", weight=1.5),
        ),
        reference_facts=reference_facts,
    )
    question = InterviewQuestion(
        id=str(uuid4()),
        session_id=session.id,
        order=0,
        category="project",
        is_anchor=True,
        prompt=DEEP_DIVE_PROMPT,
        knowledge_point_id=DEEP_DIVE_KNOWLEDGE_POINT,
        rubric_version="dialog-v1",
        signals_json=json.dumps(["项目深挖"], ensure_ascii=False),
        rubric_json=json.dumps(rubric_to_dict(rubric), ensure_ascii=False),
    )
    db.add(question)
    db.flush()

    answer_hash = hashlib.sha256(merged.encode("utf-8")).hexdigest()
    db.add(
        AnswerAttempt(
            id=str(uuid4()),
            session_id=session.id,
            question_id=question.id,
            client_submission_id=f"dialog-{session.id}",
            primary_attempt_kind="primary",
            status="submitted",
            answer_text=merged,
            answer_text_hash=answer_hash,
            payload_hash=answer_hash,
        )
    )
    session.total_questions = (
        db.scalar(
            select(func.count(InterviewQuestion.id)).where(
                InterviewQuestion.session_id == session.id
            )
        )
        or 0
    )
    # 衔接语：项目对话 → 知识环节（静态模板，ponytail：够用且零成本）
    _add_message(
        db,
        session,
        "interviewer",
        "好，项目就聊到这里。下面换几个通用的技术问题，考察一下基础功底。",
        "bridge",
    )
    session.stage = "knowledge"
    db.commit()


def _generate_next_question(
    db: Session,
    session: InterviewSession,
    provider: FollowupDecisionProvider | None,
    turn_no: int,
) -> None:
    payload = {
        "project_facts": _project_reference_facts(db, session),
        "dialog_history": [
            {
                "role": "面试官" if d.role == "interviewer" else "候选人",
                "content": d.content,
            }
            for d in _dialogs(db, session.id)
        ],
        "rounds_used": _rounds_used(db, session.id),
        "rounds_max": DIALOG_MAX_ROUNDS,
    }
    question = None
    saturated = False
    if provider is not None and hasattr(provider, "generate_interviewer_turn"):
        try:
            decision = provider.generate_interviewer_turn(payload)
            question = decision["question"]
            saturated = decision["saturated"]
        except AssessmentProviderError as exc:
            logger.warning("对话出题降级为备用问题：provider 错误 code=%s", exc.code)
            question = None
    if question is None:
        rounds = _rounds_used(db, session.id)
        question = FALLBACK_QUESTIONS[rounds % len(FALLBACK_QUESTIONS)]
        _add_message(
            db, session, "interviewer", question, "dialog", "fallback"
        )
        return
    if saturated and _rounds_used(db, session.id) >= DIALOG_MIN_ROUNDS:
        _finish_dialog(db, session, provider, closing_question=question)
        return
    _add_message(
        db,
        session,
        "interviewer",
        question,
        "dialog",
        _heuristic_tag(question),
    )


def handle_dialog_answer(
    db: Session,
    session_id: str,
    text: str,
    provider: FollowupDecisionProvider | None,
) -> dict:
    """候选人在 intro / 深挖 / wrap_up 阶段的输入。"""
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    if session.mode != "dialog":
        raise ConflictError("该会话不是对话式面试")
    if session.stage not in ("intro", "project_dialog", "wrap_up"):
        raise ConflictError("当前阶段不需要对话输入")
    if not text.strip():
        raise InvalidAnswerError("回答不能为空")
    if session.stage == "wrap_up":
        _add_message(db, session, "candidate", text.strip(), "wrapup")
        session.stage = "completed"
        session.status = "completed"
        db.commit()
        return {"stage": "completed"}

    turn_no = _next_turn_no(db, session_id)
    db.add(
        ProjectDialog(
            id=str(uuid4()),
            session_id=session_id,
            turn_no=turn_no,
            role="candidate",
            content=text.strip(),
            kind="dialog",
        )
    )
    if session.stage == "intro":
        session.stage = "project_dialog"
        db.commit()
        _generate_next_question(db, session, provider, turn_no)
        return {"stage": "project_dialog"}

    rounds_used = _rounds_used(db, session_id)
    if rounds_used >= DIALOG_MAX_ROUNDS:
        _finish_dialog(db, session, provider)
        return {"stage": "knowledge"}
    _generate_next_question(db, session, provider, turn_no)
    return {"stage": session.stage}


def finish_dialog_early(db: Session, session_id: str) -> dict:
    """候选人主动提前结束深挖。"""
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    if session.mode != "dialog" or session.stage != "project_dialog":
        raise ConflictError("当前不在项目深挖阶段")
    _finish_dialog(db, session, None)
    return {"stage": "knowledge"}


def enter_wrap_up(db: Session, session: InterviewSession) -> None:
    """知识题全部答完后调用：写反问轮。"""
    if session.stage != "knowledge":
        return
    _add_message(db, session, "interviewer", WRAPUP_MESSAGE, "wrapup")
    session.stage = "wrap_up"
    db.commit()


def skip_wrap_up(db: Session, session_id: str) -> dict:
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    if session.mode != "dialog" or session.stage != "wrap_up":
        raise ConflictError("当前不在反问阶段")
    session.stage = "completed"
    session.status = "completed"
    db.commit()
    return {"stage": "completed"}


def session_timeline(db: Session, session: InterviewSession) -> list[dict]:
    """统一消息时间线：所有会话（classic/dialog）的问答按真实时序排列。

    dialog 模式含开场白/深挖轮/衔接语/反问；classic 模式只有知识问答。
    教练便签（练习反馈）跟在对应回答之后。未问到的题不进时间线。
    """
    items: list[dict] = []
    dialogs = _dialogs(db, session.id) if session.mode == "dialog" else []
    wrapup = next((d for d in dialogs if d.kind == "wrapup"), None)

    def _push_message(d: ProjectDialog) -> None:
        items.append(
            {
                "role": d.role,
                "kind": d.kind,
                "content": d.content,
                "tag": d.heuristic_tag,
            }
        )

    for d in dialogs:
        if d.kind == "wrapup":
            continue
        _push_message(d)

    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(
                InterviewQuestion.session_id == session.id,
                *( [InterviewQuestion.order != 0] if session.mode == "dialog" else [] )
            )
            .order_by(InterviewQuestion.order)
        )
    )
    answers = {
        answer.question_id: answer
        for answer in db.scalars(
            select(AnswerAttempt).where(AnswerAttempt.session_id == session.id)
        )
    }
    followups_by_question: dict[str, list[InterviewFollowup]] = {}
    for followup in db.scalars(
        select(InterviewFollowup)
        .where(InterviewFollowup.session_id == session.id)
        .order_by(InterviewFollowup.round)
    ):
        followups_by_question.setdefault(followup.question_id, []).append(followup)
    feedbacks = feedback_for_session(db, session.id)

    for question in questions:
        answer = answers.get(question.id)
        if answer is None:
            # 还没问到的题不进时间线，避免未来问题提前泄露
            continue
        items.append(
            {
                "role": "interviewer",
                "kind": "question",
                "content": question.prompt,
                "question_id": question.id,
            }
        )
        items.append(
            {
                "role": "candidate",
                "kind": "answer",
                "content": answer.answer_text,
                "question_id": question.id,
            }
        )
        feedback = feedbacks.get(question.id)
        if feedback is not None:
            items.append(
                {
                    "role": "coach",
                    "kind": "coach",
                    "content": feedback.content,
                    "question_id": question.id,
                }
            )
        for followup in followups_by_question.get(question.id, []):
            items.append(
                {
                    "role": "interviewer",
                    "kind": "followup",
                    "content": followup.question_text,
                    "question_id": question.id,
                }
            )
            if followup.answer_text:
                items.append(
                    {
                        "role": "candidate",
                        "kind": "followup_answer",
                        "content": followup.answer_text,
                        "question_id": question.id,
                    }
                )
    if wrapup is not None:
        _push_message(wrapup)
        wrapup_answer = next(
            (d for d in dialogs if d.kind == "wrapup" and d.role == "candidate"),
            None,
        )
        if wrapup_answer is not None:
            _push_message(wrapup_answer)
    return items
