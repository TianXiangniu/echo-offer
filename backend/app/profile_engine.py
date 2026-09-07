from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Iterable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AnswerAttempt,
    AssessmentRun,
    CandidateKnowledgeState,
    CandidateProfile,
    InterviewQuestion,
    InterviewSession,
    InterviewTarget,
    LearningRecommendation,
    ProfileSnapshot,
    QuestionSkill,
    RoleSkillRequirement,
    SkillCatalog,
    RubricObservation,
)


# 练习不等于会了：drill 样本降权，隔了几天还能答出来的 verification 升权。
SAMPLE_KIND_WEIGHTS = {"interview": 1.0, "drill": 0.5, "verification": 1.2}


@dataclass(frozen=True, slots=True)
class SkillSample:
    level: int
    confidence: float
    assessed_at: datetime
    serious_error: bool = False
    session_id: str | None = None
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class AggregatedSkill:
    current_level: int
    confidence: float
    valid_sample_count: int
    trend: str
    serious_error_count: int


DEFAULT_SKILLS = {
    "project.ownership_and_context": ("项目表达与负责边界", "项目"),
    "project.architecture_tradeoffs": ("架构取舍", "项目"),
    "project.evaluation_and_reproducibility": ("效果评估与复现", "项目"),
    "rag.retrieval_diagnosis": ("RAG召回排查", "Agent与RAG"),
    "rag.query_rewrite_and_hybrid_retrieval": ("查询改写与混合检索", "Agent与RAG"),
    "agent_runtime.tool_calling": ("Agent工具调用", "Agent运行时"),
    "engineering.latency_diagnosis": ("线上延迟排查", "工程实践"),
    "engineering.output_safety": ("模型输出安全", "工程实践"),
}

_GRAPH_KIND_TO_SKILL = {
    "opening": "project.ownership_and_context",
    "project": "project.ownership_and_context",
    "architecture": "project.architecture_tradeoffs",
    "challenge": "project.architecture_tradeoffs",
    "tradeoff": "project.architecture_tradeoffs",
    "evidence": "project.evaluation_and_reproducibility",
}


def _datetime_key(value: datetime) -> datetime:
    """Make SQLite-naive and timezone-aware datetimes comparable."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def aggregate_skill_samples(
    samples: Iterable[SkillSample],
    *,
    now: datetime | None = None,
) -> AggregatedSkill:
    ordered = sorted(samples, key=lambda item: _datetime_key(item.assessed_at), reverse=True)
    if not ordered:
        return AggregatedSkill(0, 0.0, 0, "insufficient_data", 0)

    # A recent observation counts more, but older observations remain visible.
    weights = [
        max(1, 5 - index) * max(0.1, item.weight)
        for index, item in enumerate(ordered[:5])
    ]
    selected = ordered[:5]
    total_weight = sum(weights)
    weighted_level = sum(item.level * weight for item, weight in zip(selected, weights)) / total_weight
    weighted_confidence = sum(
        max(0.0, min(1.0, item.confidence)) * weight
        for item, weight in zip(selected, weights)
    ) / total_weight
    confidence = weighted_confidence * min(1.0, len(ordered) / 3)

    if len(ordered) < 2:
        trend = "insufficient_data"
    else:
        latest = ordered[0].level
        previous = sum(item.level for item in ordered[1:3]) / len(ordered[1:3])
        delta = latest - previous
        trend = "improving" if delta >= 0.5 else "declining" if delta <= -0.5 else "stable"

    return AggregatedSkill(
        current_level=max(0, min(4, int(round(weighted_level)))),
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        valid_sample_count=len(ordered),
        trend=trend,
        serious_error_count=sum(1 for item in ordered if item.serious_error),
    )


def recommendation_priority(
    *,
    current_level: int,
    target_level: int,
    importance_weight: float,
    serious_error_count: int,
    sample_count: int,
) -> str:
    if sample_count == 0:
        return "insufficient_data"
    gap = target_level - current_level
    if gap <= 0:
        return "low"
    if serious_error_count > 0 or (gap >= 2 and importance_weight >= 0.75):
        return "high"
    return "medium"


def _ensure_skill(db: Session, knowledge_point_id: str) -> SkillCatalog:
    skill = db.get(SkillCatalog, knowledge_point_id)
    if skill is not None:
        return skill
    canonical_name, category = DEFAULT_SKILLS.get(
        knowledge_point_id,
        (knowledge_point_id.replace(".", " / "), "其他"),
    )
    skill = SkillCatalog(
        id=knowledge_point_id,
        canonical_name=canonical_name,
        category=category,
        aliases_json="[]",
        description="",
    )
    db.add(skill)
    db.flush()
    return skill


def _ensure_question_skill(db: Session, question: InterviewQuestion) -> SkillCatalog:
    skill_id = str(question.knowledge_point_id)
    if skill_id.startswith("graph."):
        skill_id = _GRAPH_KIND_TO_SKILL.get(
            question.category,
            skill_id.removeprefix("graph."),
        )
    skill = _ensure_skill(db, skill_id)
    mapping = db.scalar(
        select(QuestionSkill).where(
            QuestionSkill.question_id == question.id,
            QuestionSkill.skill_id == skill.id,
        )
    )
    if mapping is None:
        db.add(
            QuestionSkill(
                id=str(uuid4()),
                question_id=question.id,
                skill_id=skill.id,
                weight=1.0,
            )
        )
        db.flush()
    return skill


def get_or_create_candidate_profile(
    db: Session,
    *,
    user_id: str,
    direction: str,
    level: str,
    target_title: str,
) -> CandidateProfile:
    profile = db.scalar(
        select(CandidateProfile).where(
            CandidateProfile.user_id == user_id,
            CandidateProfile.direction == direction,
            CandidateProfile.level == level,
            CandidateProfile.target_title == target_title,
        )
    )
    if profile is not None:
        return profile
    profile = CandidateProfile(
        id=str(uuid4()),
        user_id=user_id,
        direction=direction,
        level=level,
        target_title=target_title,
        summary="还没有足够的面试记录。完成一场面试后，这里会开始记录你的能力变化。",
    )
    db.add(profile)
    db.flush()
    return profile


def _ensure_role_requirement(
    db: Session,
    *,
    direction: str,
    level: str,
    skill: SkillCatalog,
) -> RoleSkillRequirement:
    requirement = db.scalar(
        select(RoleSkillRequirement).where(
            RoleSkillRequirement.direction == direction,
            RoleSkillRequirement.level == level,
            RoleSkillRequirement.skill_id == skill.id,
        )
    )
    if requirement is not None:
        return requirement
    requirement = RoleSkillRequirement(
        id=str(uuid4()),
        direction=direction,
        level=level,
        skill_id=skill.id,
        target_level=3 if skill.category != "工程实践" else 2,
        importance_weight=1.0 if skill.category in {"Agent与RAG", "项目"} else 0.8,
    )
    db.add(requirement)
    db.flush()
    return requirement


def _recommendation_text(skill: SkillCatalog, state: CandidateKnowledgeState, requirement) -> tuple[str, list[str], list[str]]:
    gap = requirement.target_level - state.current_level
    if state.valid_sample_count == 0:
        reason = f"还没有足够的回答可以判断“{skill.canonical_name}”，先积累几次相关回答。"
        actions = [f"先回答一道{skill.canonical_name}相关问题", "说清楚自己的做法、原因和限制"]
        criteria = ["能结合具体场景讲清楚方案和取舍"]
    elif gap > 0:
        reason = f"最近的回答提到了“{skill.canonical_name}”，但做法、边界或验证还可以说得更具体。"
        actions = [f"复习{skill.canonical_name}的核心机制", "用一个真实项目场景重新回答相关问题", "补充边界、故障和验证方式"]
        criteria = ["连续两次相关回答都能讲清方案、原因和限制"]
    else:
        reason = f"“{skill.canonical_name}”最近保持得不错，可以继续用真实案例巩固。"
        actions = ["整理一个可复现的项目案例", "继续关注异常情况和方案取舍"]
        criteria = ["能结合场景说明方案和取舍"]
    return reason, actions, criteria


def build_learning_recommendations(
    db: Session,
    profile: CandidateProfile,
) -> list[LearningRecommendation]:
    states = list(
        db.scalars(
            select(CandidateKnowledgeState).where(
                CandidateKnowledgeState.profile_id == profile.id
            )
        )
    )
    recommendations: list[LearningRecommendation] = []
    for state in states:
        skill = db.get(SkillCatalog, state.skill_id)
        if skill is None:
            continue
        requirement = _ensure_role_requirement(
            db,
            direction=profile.direction,
            level=profile.level,
            skill=skill,
        )
        priority = recommendation_priority(
            current_level=state.current_level,
            target_level=requirement.target_level,
            importance_weight=requirement.importance_weight,
            serious_error_count=state.serious_error_count,
            sample_count=state.valid_sample_count,
        )
        reason, actions, criteria = _recommendation_text(skill, state, requirement)
        recommendations.append(
            LearningRecommendation(
                id=str(uuid4()),
                profile_id=profile.id,
                profile_snapshot_id=profile.current_snapshot_id or "pending",
                skill_id=skill.id,
                priority=priority,
                reason=reason,
                actions_json=json.dumps(actions, ensure_ascii=False),
                success_criteria_json=json.dumps(criteria, ensure_ascii=False),
                status="recommended",
            )
        )
    priority_order = {"high": 0, "medium": 1, "insufficient_data": 2, "low": 3}
    recommendations.sort(key=lambda item: priority_order.get(item.priority, 4))
    return recommendations


def update_candidate_profile(
    db: Session,
    session_id: str,
    *,
    commit: bool = True,
) -> CandidateProfile:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise ValueError("session not found")
    target = db.get(InterviewTarget, session.target_id)
    if target is None:
        raise ValueError("interview target not found")
    profile = (
        db.get(CandidateProfile, session.profile_id)
        if session.profile_id
        else get_or_create_candidate_profile(
            db,
            user_id=session.user_id,
            direction=target.direction,
            level=target.level,
            target_title=target.target_title,
        )
    )
    session.profile_id = profile.id

    samples_by_skill: dict[str, list[SkillSample]] = defaultdict(list)
    all_sessions = list(
        db.scalars(
            select(InterviewSession).where(InterviewSession.profile_id == profile.id)
        )
    )
    for candidate_session in all_sessions:
        session_samples: dict[str, list[SkillSample]] = defaultdict(list)
        questions = list(
            db.scalars(
                select(InterviewQuestion).where(
                    InterviewQuestion.session_id == candidate_session.id
                )
            )
        )
        for question in questions:
            skill = _ensure_question_skill(db, question)
            answer = db.scalar(
                select(AnswerAttempt)
                .where(
                    AnswerAttempt.session_id == candidate_session.id,
                    AnswerAttempt.question_id == question.id,
                    AnswerAttempt.status.in_(("submitted", "explicit_unknown")),
                )
                .order_by(AnswerAttempt.created_at.desc(), AnswerAttempt.id.desc())
            )
            if answer is None:
                continue
            run = db.scalar(
                select(AssessmentRun)
                .where(AssessmentRun.answer_id == answer.id)
                .order_by(AssessmentRun.attempt_number.desc(), AssessmentRun.created_at.desc())
            )
            if run is None or run.status != "valid" or run.aggregate_level is None:
                continue
            rubric_items = list(
                db.scalars(
                    select(RubricObservation).where(
                        RubricObservation.assessment_run_id == run.id,
                        RubricObservation.validity == "valid",
                    )
                )
            )
            # A level-zero explicit unknown is valid, but it is not a technical error.
            serious_error = run.aggregate_level > 0 and any(
                item.level == 0 for item in rubric_items
            )
            session_samples[skill.id].append(
                SkillSample(
                    level=run.aggregate_level,
                    confidence=run.aggregate_confidence or 0.0,
                    assessed_at=run.created_at,
                    serious_error=serious_error,
                )
            )

        # A session is one observation for a skill. This prevents a long interview
        # with many questions from outweighing a shorter interview in the profile.
        for skill_id, question_samples in session_samples.items():
            assessed_at = max(
                (item.assessed_at for item in question_samples),
                key=_datetime_key,
            )
            samples_by_skill[skill_id].append(
                SkillSample(
                    level=round(
                        sum(item.level for item in question_samples) / len(question_samples)
                    ),
                    confidence=sum(item.confidence for item in question_samples)
                    / len(question_samples),
                    assessed_at=assessed_at,
                    serious_error=any(item.serious_error for item in question_samples),
                    session_id=candidate_session.id,
                    weight=SAMPLE_KIND_WEIGHTS.get(candidate_session.session_kind, 1.0),
                )
            )

    for skill_id, samples in samples_by_skill.items():
        aggregate = aggregate_skill_samples(samples)
        state = db.scalar(
            select(CandidateKnowledgeState).where(
                CandidateKnowledgeState.profile_id == profile.id,
                CandidateKnowledgeState.skill_id == skill_id,
            )
        )
        if state is None:
            state = CandidateKnowledgeState(
                id=str(uuid4()),
                user_id=session.user_id,
                profile_id=profile.id,
                skill_id=skill_id,
            )
            db.add(state)
        state.current_level = aggregate.current_level
        state.confidence = aggregate.confidence
        state.valid_sample_count = aggregate.valid_sample_count
        state.trend = aggregate.trend
        state.serious_error_count = aggregate.serious_error_count
        state.first_assessed_at = min(samples, key=lambda item: _datetime_key(item.assessed_at)).assessed_at
        latest_sample = max(samples, key=lambda item: _datetime_key(item.assessed_at))
        state.last_assessed_at = latest_sample.assessed_at
        state.last_session_id = latest_sample.session_id

    db.flush()
    latest_version = db.scalar(
        select(func.max(ProfileSnapshot.version)).where(
            ProfileSnapshot.profile_id == profile.id
        )
    ) or 0
    snapshot_payload = {
        "profile_id": profile.id,
        "direction": profile.direction,
        "level": profile.level,
        "skills": [
            {
                "skill_id": state.skill_id,
                "level": state.current_level,
                "confidence": state.confidence,
                "sample_count": state.valid_sample_count,
                "trend": state.trend,
            }
            for state in db.scalars(
                select(CandidateKnowledgeState).where(
                    CandidateKnowledgeState.profile_id == profile.id
                )
            )
        ],
    }
    snapshot = ProfileSnapshot(
        id=str(uuid4()),
        profile_id=profile.id,
        source_session_id=session.id,
        version=latest_version + 1,
        profile_json=json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True),
    )
    db.add(snapshot)
    db.flush()
    profile.current_snapshot_id = snapshot.id

    recommendations = build_learning_recommendations(db, profile)
    for recommendation in recommendations:
        recommendation.profile_snapshot_id = snapshot.id
        db.add(recommendation)
    high_priority = [item for item in recommendations if item.priority == "high"]
    states = list(
        db.scalars(
            select(CandidateKnowledgeState).where(
                CandidateKnowledgeState.profile_id == profile.id
            )
        )
    )
    total_samples = sum(state.valid_sample_count for state in states)
    if high_priority:
        names = [db.get(SkillCatalog, item.skill_id).canonical_name for item in high_priority]
        profile.summary = (
            f"已积累 {total_samples} 次有效回答。当前最需要加强：{'、'.join(names[:3])}——"
            "先回看对应题目的完整回答，再用专项练习补上，过几天验证一次。"
        )
    elif states:
        strongest = max(states, key=lambda s: (s.current_level, s.confidence))
        strongest_name = db.get(SkillCatalog, strongest.skill_id).canonical_name
        weakest = min(states, key=lambda s: (s.current_level, -s.confidence))
        weakest_name = db.get(SkillCatalog, weakest.skill_id).canonical_name
        if strongest.current_level == weakest.current_level:
            profile.summary = (
                f"已积累 {total_samples} 次有效回答，各方向水平接近（当前 {weakest.current_level} / 4）。"
                "继续保持练习频率，样本越多判断越准。"
            )
        else:
            profile.summary = (
                f"已积累 {total_samples} 次有效回答。最稳的是{strongest_name}（{strongest.current_level} / 4），"
                f"相对薄弱的是{weakest_name}（{weakest.current_level} / 4）——薄弱方向练一次并延迟验证，可以更快拉平。"
            )
    else:
        profile.summary = "还没有足够的面试记录。完成一场面试后，这里会开始记录你的能力变化。"
    profile.updated_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
    return profile
