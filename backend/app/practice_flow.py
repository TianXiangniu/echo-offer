"""Practice loop: drill and verification sessions.

drill：针对画像薄弱知识点的专项小会话（2 道本知识点平行题 + 1 道相邻知识点题），
复用完整评分链路；verification：练习完成 3 天后的单题验证会话。
画像聚合本来按 skill_id（即 knowledge_point_id）取最近样本，drill/verification
会话的评分自动计入画像，无需新的评分通道。
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import WORKFLOW_VERSION
from .models import (
    CandidateProfile,
    InterviewQuestion,
    InterviewSession,
    InterviewTarget,
    LearningRecommendation,
    Resume,
    ResumeProject,
    ensure_utc,
    utc_now,
)
from .question_bank import QUESTION_TEMPLATES, QuestionSpec
from .rubrics import build_rubric, rubric_to_dict
from .workflow_common import ConflictError, NotFoundError, _recent_template_ids

VERIFICATION_WAIT_DAYS = 3
DRILL_TARGET_QUESTION_COUNT = 2
DRILL_ADJACENT_QUESTION_COUNT = 1


def _spec_from_template(order: int, knowledge_point_id: str, template) -> QuestionSpec:
    return QuestionSpec(
        order=order,
        category="reliability",
        is_anchor=False,
        prompt=template.prompt,
        knowledge_point_id=knowledge_point_id,
        rubric_version="alpha-local-v1",
        signals=template.signals,
        reference_facts=template.reference_facts,
        template_id=template.template_id,
        rubric_weights=template.rubric_weights,
        criteria_override=template.criteria_override,
    )


def _get_recommendation(db: Session, recommendation_id: str) -> LearningRecommendation:
    recommendation = db.get(LearningRecommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("recommendation not found")
    return recommendation


def _profile_user_id(db: Session, recommendation: LearningRecommendation) -> str:
    profile = db.get(CandidateProfile, recommendation.profile_id)
    if profile is None:
        raise NotFoundError("profile not found")
    return profile.user_id


def _latest_project_and_target(db: Session, user_id: str):
    project = db.scalar(
        select(ResumeProject)
        .join(Resume, Resume.id == ResumeProject.resume_id)
        .where(Resume.user_id == user_id)
        .order_by(ResumeProject.created_at.desc(), ResumeProject.project_version.desc())
    )
    if project is None:
        raise NotFoundError("resume project not found")
    target = db.scalar(select(InterviewTarget).where(InterviewTarget.user_id == user_id))
    if target is None:
        raise NotFoundError("interview target not found")
    return project, target


def _pick_templates(
    knowledge_point_id: str,
    count: int,
    excluded_template_ids: set[str],
    rng: random.Random,
) -> list[QuestionSpec]:
    pool = list(QUESTION_TEMPLATES.get(knowledge_point_id, ()))
    if not pool:
        return []
    fresh = [template for template in pool if template.template_id not in excluded_template_ids]
    candidates = fresh or pool
    rng.shuffle(candidates)
    return [
        _spec_from_template(order, knowledge_point_id, template)
        for order, template in enumerate(candidates[:count], start=1)
    ]


def _drill_specs(
    skill_id: str,
    excluded_template_ids: set[str],
    rng: random.Random,
    total: int = 3,
) -> list[QuestionSpec]:
    """优先抽薄弱点自己的平行题；项目类知识点没有题池时用相邻知识点基础题补足。"""
    specs: list[QuestionSpec] = []
    if QUESTION_TEMPLATES.get(skill_id):
        specs = _pick_templates(skill_id, DRILL_TARGET_QUESTION_COUNT, excluded_template_ids, rng)
    used = excluded_template_ids | {spec.template_id for spec in specs}
    adjacent_points = [point for point in QUESTION_TEMPLATES if point != skill_id]
    rng.shuffle(adjacent_points)
    for point in adjacent_points:
        if len(specs) >= total:
            break
        got = _pick_templates(point, 1, used, rng)
        if got:
            specs += got
            used |= {spec.template_id for spec in got}
    return [replace(spec, order=index) for index, spec in enumerate(specs, start=1)]


def _create_practice_session(
    db: Session,
    recommendation: LearningRecommendation | None,
    specs: list[QuestionSpec],
    session_kind: str,
    *,
    profile_id: str | None = None,
) -> InterviewSession:
    resolved_profile_id = profile_id or (recommendation.profile_id if recommendation else None)
    profile = db.get(CandidateProfile, resolved_profile_id)
    if profile is None:
        raise NotFoundError("profile not found")
    project, target = _latest_project_and_target(db, profile.user_id)
    session = InterviewSession(
        id=str(uuid4()),
        user_id=profile.user_id,
        resume_project_id=project.id,
        target_id=target.id,
        profile_id=profile.id,
        status="in_progress",
        current_question_index=0,
        total_questions=len(specs),
        followup_budget_used=0,
        session_kind=session_kind,
        source_recommendation_id=recommendation.id if recommendation else None,
        workflow_version=WORKFLOW_VERSION,
        session_version=1,
    )
    db.add(session)
    db.flush()
    for spec in specs:
        db.add(
            InterviewQuestion(
                id=str(uuid4()),
                session_id=session.id,
                order=spec.order,
                category=spec.category,
                is_anchor=spec.is_anchor,
                prompt=spec.prompt,
                knowledge_point_id=spec.knowledge_point_id,
                template_id=spec.template_id or None,
                rubric_version=spec.rubric_version,
                signals_json=json.dumps(spec.signals, ensure_ascii=False),
                rubric_json=json.dumps(
                    rubric_to_dict(build_rubric(spec)), ensure_ascii=False
                ),
            )
        )
    return session


def _existing_open_practice_session(
    db: Session, recommendation_id: str, session_kind: str
) -> InterviewSession | None:
    return db.scalar(
        select(InterviewSession).where(
            InterviewSession.source_recommendation_id == recommendation_id,
            InterviewSession.session_kind == session_kind,
            InterviewSession.status == "in_progress",
            InterviewSession.archived_at.is_(None),
        )
    )


def create_drill_session(db: Session, recommendation_id: str) -> dict:
    recommendation = _get_recommendation(db, recommendation_id)
    open_session = _existing_open_practice_session(db, recommendation_id, "drill")
    if open_session is not None:
        return {"session_id": open_session.id, "session_kind": "drill"}

    user_id = _profile_user_id(db, recommendation)
    rng = random.Random()
    excluded = _recent_template_ids(db, user_id, look_back_sessions=2)
    specs = _drill_specs(recommendation.skill_id, excluded, rng)
    if not specs:
        raise ConflictError("该知识点暂无专项练习题，请先回看对应回答")

    recommendation.status = "in_progress"
    session = _create_practice_session(db, recommendation, specs, "drill")
    db.commit()
    return {"session_id": session.id, "session_kind": "drill"}


def create_verification_session(db: Session, recommendation_id: str) -> dict:
    recommendation = _get_recommendation(db, recommendation_id)
    if recommendation.practice_completed_at is None:
        raise ConflictError("先完成一次专项练习，再进行验证")
    practice_at = ensure_utc(recommendation.practice_completed_at)
    ready_at = practice_at + timedelta(days=VERIFICATION_WAIT_DAYS)
    if utc_now() < ready_at:
        raise ConflictError("练习内容还需要时间消化，建议过几天再验证")
    open_session = _existing_open_practice_session(db, recommendation_id, "verification")
    if open_session is not None:
        return {"session_id": open_session.id, "session_kind": "verification"}

    user_id = _profile_user_id(db, recommendation)
    rng = random.Random()
    excluded = _recent_template_ids(db, user_id, look_back_sessions=2)
    specs = _pick_templates(recommendation.skill_id, 1, excluded, rng)
    if not specs:
        adjacent_points = [
            point for point in QUESTION_TEMPLATES if point != recommendation.skill_id
        ]
        rng.shuffle(adjacent_points)
        for point in adjacent_points:
            specs = _pick_templates(point, 1, excluded, rng)
            if specs:
                break
    if not specs:
        raise ConflictError("该知识点暂无验证题目")
    session = _create_practice_session(db, recommendation, specs, "verification")
    db.commit()
    return {"session_id": session.id, "session_kind": "verification"}


def sync_practice_recommendation(db: Session, session: InterviewSession) -> None:
    """评分收尾时同步建议状态：drill 记录练习时间，verification 完成建议。"""
    if not session.source_recommendation_id or session.session_kind not in {
        "drill",
        "verification",
    }:
        return
    recommendation = db.get(LearningRecommendation, session.source_recommendation_id)
    if recommendation is None:
        return
    if session.session_kind == "drill":
        if recommendation.practice_completed_at is None:
            recommendation.practice_completed_at = utc_now()
    elif session.status == "completed":
        recommendation.status = "completed"


def create_open_drill(db: Session, skill_id: str | None = None) -> dict:
    """无薄弱建议时也能练：随机（或指定）知识点发起 3 题专项练习。"""
    profile = db.scalar(
        select(CandidateProfile).order_by(CandidateProfile.created_at.desc())
    )
    if profile is None:
        raise NotFoundError("profile not found")
    pool = list(QUESTION_TEMPLATES)
    if skill_id:
        if skill_id not in QUESTION_TEMPLATES:
            raise NotFoundError("unknown knowledge point")
        chosen_point = skill_id
    else:
        import random as random_module

        chosen_point = random_module.choice(pool)
    rng = random.Random()
    excluded = _recent_template_ids(db, profile.user_id, look_back_sessions=2)
    specs = _drill_specs(chosen_point, excluded, rng)
    if not specs:
        raise ConflictError("该知识点暂无专项练习题")
    session = _create_practice_session(db, None, specs, "drill", profile_id=profile.id)
    db.commit()
    return {"session_id": session.id, "session_kind": "drill", "skill_id": chosen_point}
