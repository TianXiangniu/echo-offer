"""画像 v2 的派生计算：新鲜度、衰减 readiness、证据链、练→验有效性、追问角度、今日训练卡。

全部从现有表派生（skill_study_log / project_dialogs / profile_snapshots / 会话样本），
不持久化任何新数据——计划与度量是"活着的"，每次打开按当前状态重算。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnswerAttempt,
    AssessmentRun,
    CandidateKnowledgeState,
    CandidateProfile,
    InterviewFollowup,
    InterviewQuestion,
    InterviewSession,
    LearningRecommendation,
    ProjectDialog,
    SkillStudyLog,
    ensure_utc,
    utc_now,
)

FRESH_DAYS = 3
COOLING_DAYS = 10
STALE_DECAY = 0.8
EVIDENCE_LIMIT = 3


def _days_since(value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, (utc_now() - ensure_utc(value)).days)


def freshness_of(last_assessed_at: datetime | None) -> str:
    days = _days_since(last_assessed_at)
    if days is None:
        return "no_data"
    if days <= FRESH_DAYS:
        return "fresh"
    if days <= COOLING_DAYS:
        return "cooling"
    return "stale"


def studied_skill_ids(db: Session, user_id: str) -> set[str]:
    return set(
        db.scalars(select(SkillStudyLog.skill_id).where(SkillStudyLog.user_id == user_id))
    )


def recent_answers_for_skill(
    db: Session, profile_id: str, skill_id: str, limit: int = EVIDENCE_LIMIT
) -> list[dict]:
    """该技能最近 N 次有效回答：题目、等级、点评、场次——证据链下钻的数据源。"""
    rows = db.execute(
        select(
            AnswerAttempt.id,
            InterviewQuestion.prompt,
            AssessmentRun.aggregate_level,
            AssessmentRun.commentary,
            InterviewSession.id,
            AssessmentRun.created_at,
        )
        .join(AssessmentRun, AssessmentRun.answer_id == AnswerAttempt.id)
        .join(InterviewQuestion, AnswerAttempt.question_id == InterviewQuestion.id)
        .join(InterviewSession, AnswerAttempt.session_id == InterviewSession.id)
        .where(
            InterviewSession.profile_id == profile_id,
            InterviewQuestion.knowledge_point_id == skill_id,
            InterviewSession.archived_at.is_(None),
            AssessmentRun.status == "valid",
            AnswerAttempt.status.in_(("submitted", "explicit_unknown")),
        )
        .order_by(AssessmentRun.created_at.desc())
        .limit(limit * 3)
    ).all()
    # 同一回答多次评分只保留最新一次
    seen: set[str] = set()
    evidence = []
    for answer_id, prompt, level, commentary, session_id, _ in rows:
        if answer_id in seen or level is None:
            continue
        seen.add(answer_id)
        evidence.append(
            {
                "prompt": prompt,
                "level": level,
                "commentary": commentary or "",
                "session_id": session_id,
            }
        )
        if len(evidence) >= limit:
            break
    return evidence


def question_angle_distribution(db: Session, profile_id: str) -> list[dict]:
    """深挖对话中被追问的角度分布（fallback/收束不计入）。"""
    session_ids = list(
        db.scalars(
            select(InterviewSession.id).where(
                InterviewSession.profile_id == profile_id,
                InterviewSession.archived_at.is_(None),
            )
        )
    )
    if not session_ids:
        return []
    tags = db.scalars(
        select(ProjectDialog.heuristic_tag).where(
            ProjectDialog.session_id.in_(session_ids),
            ProjectDialog.role == "interviewer",
            ProjectDialog.heuristic_tag.is_not(None),
            ProjectDialog.heuristic_tag.not_in(("fallback", "收束")),
        )
    )
    counter = Counter(tags)
    return [{"tag": tag, "count": count} for tag, count in counter.most_common()]


def practice_effectiveness(db: Session, profile_id: str) -> dict:
    """练→验有效性：每个 drill 样本与其后第一个同技能样本配对，验证等级 ≥ 练习前即有效。"""
    rows = db.execute(
        select(
            InterviewQuestion.knowledge_point_id,
            InterviewSession.session_kind,
            AssessmentRun.aggregate_level,
            AssessmentRun.created_at,
        )
        .join(AnswerAttempt, AssessmentRun.answer_id == AnswerAttempt.id)
        .join(InterviewQuestion, AnswerAttempt.question_id == InterviewQuestion.id)
        .join(InterviewSession, AnswerAttempt.session_id == InterviewSession.id)
        .where(
            InterviewSession.profile_id == profile_id,
            InterviewSession.archived_at.is_(None),
            AssessmentRun.status == "valid",
            AssessmentRun.aggregate_level.is_not(None),
            AnswerAttempt.status.in_(("submitted", "explicit_unknown")),
        )
        .order_by(AssessmentRun.created_at.asc())
    ).all()

    # 按技能整理时间序列（同一时刻取均值场景罕见，直接顺序走）
    series: dict[str, list[tuple[str, int]]] = {}
    for knowledge_point_id, kind, level, _ in rows:
        if level is None:
            continue
        series.setdefault(knowledge_point_id, []).append((kind or "interview", level))

    pairs = 0
    effective = 0
    for samples in series.values():
        pending_drill = None
        for kind, level in samples:
            if kind == "drill":
                if pending_drill is None:
                    pending_drill = level
            elif pending_drill is not None:
                pairs += 1
                if level >= pending_drill:
                    effective += 1
                pending_drill = None
    return {"pairs": pairs, "effective": effective}


def verifiable_count(db: Session, profile_id: str) -> int:
    from datetime import timedelta

    count = 0
    for recommendation in db.scalars(
        select(LearningRecommendation).where(
            LearningRecommendation.profile_id == profile_id,
            LearningRecommendation.status != "dismissed",
        )
    ):
        if recommendation.practice_completed_at is None:
            continue
        practice_at = ensure_utc(recommendation.practice_completed_at)
        if utc_now() >= practice_at + timedelta(days=3):
            count += 1
    return count


def build_today_plan(
    db: Session,
    profile: CandidateProfile,
    states: list[CandidateKnowledgeState],
    target_date: datetime | None,
) -> list[dict]:
    """今日训练卡：按 到期验证 > 生疏薄弱 > 未学薄弱 > 常规薄弱 > 随机 的优先级取前 3 个动作。

    纯规则引擎，动态重算，不持久化。冲刺模式（距面试 ≤3 天）只推验证与复习。
    """
    studied = studied_skill_ids(db, profile.user_id)
    skills = {state.skill_id: state for state in states}
    names = {state.skill_id: state.skill_id for state in states}
    from .models import SkillCatalog

    for skill in db.scalars(select(SkillCatalog)):
        names[skill.id] = skill.canonical_name

    def _weak(state: CandidateKnowledgeState) -> bool:
        return state.current_level < 3

    candidates: list[dict] = []

    # 1. 到期验证
    for recommendation in db.scalars(
        select(LearningRecommendation).where(
            LearningRecommendation.profile_id == profile.id,
            LearningRecommendation.status != "dismissed",
        )
    ):
        if recommendation.practice_completed_at is None or recommendation.status == "completed":
            continue
        practice_at = ensure_utc(recommendation.practice_completed_at)
        ready = utc_now() >= practice_at + timedelta(days=3)
        if ready:
            candidates.append(
                {
                    "type": "verify",
                    "skill_id": recommendation.skill_id,
                    "skill_name": names.get(recommendation.skill_id, recommendation.skill_id),
                    "reason": "练习已完成 3 天以上，验证一下是否真的掌握",
                    "recommendation_id": recommendation.id,
                }
            )

    sprint = False
    if target_date is not None:
        days_left = (ensure_utc(target_date) - utc_now()).days
        sprint = 0 <= days_left <= 3

    # 2. 生疏薄弱（>10 天未练且低于目标）
    for state in states:
        if _weak(state) and freshness_of(state.last_assessed_at) == "stale":
            candidates.append(
                {
                    "type": "review",
                    "skill_id": state.skill_id,
                    "skill_name": names.get(state.skill_id, state.skill_id),
                    "reason": f"等级 {state.current_level} / 4 且已 { _days_since(state.last_assessed_at) } 天未练，先复习再练",
                }
            )

    if not sprint:
        # 3. 未学薄弱
        for state in states:
            if _weak(state) and state.skill_id not in studied:
                candidates.append(
                    {
                        "type": "study",
                        "skill_id": state.skill_id,
                        "skill_name": names.get(state.skill_id, state.skill_id),
                        "reason": "这个薄弱点还没看过讲解，先学再练",
                    }
                )
        # 4. 常规薄弱
        for state in states:
            if _weak(state):
                candidates.append(
                    {
                        "type": "practice",
                        "skill_id": state.skill_id,
                        "skill_name": names.get(state.skill_id, state.skill_id),
                        "reason": f"等级 {state.current_level} / 4，专项练一次",
                    }
                )

    # 去重（同技能保留首个动作）
    seen: set[str] = set()
    plan: list[dict] = []
    for action in candidates:
        if action["skill_id"] in seen:
            continue
        seen.add(action["skill_id"])
        plan.append(action)
        if len(plan) >= 3:
            break
    if not plan and not sprint:
        plan.append(
            {
                "type": "random",
                "skill_id": None,
                "skill_name": "随机知识点",
                "reason": "没有明显薄弱点，随机练一轮保持手感",
            }
        )
    return plan
