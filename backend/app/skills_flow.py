"""知识点 Wiki 流程：列表、详情、学习标记、深讲生成。

内容三层：预置骨架（种子）→ 深讲（按需生成缓存）→ 掌握度（评分驱动，实时查询）。
"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnswerAttempt,
    AssessmentRun,
    CandidateKnowledgeState,
    CandidateProfile,
    InterviewQuestion,
    SkillCatalog,
    SkillStudyLog,
    SkillWiki,
    utc_now,
    CommunityQuestion,
    InterviewSession,
)
from .prompts import WIKI_PROMPT_VERSION
from .question_bank import QUESTION_TEMPLATES
from .skills_seed import ensure_skill_wiki_seeds
from .workflow_common import NotFoundError


def _local_profile(db: Session) -> CandidateProfile | None:
    return db.scalar(
        select(CandidateProfile).order_by(CandidateProfile.created_at.desc())
    )


def _mastery_by_skill(db: Session, user_id: str | None) -> dict[str, dict]:
    """跨 profile 聚合掌握度：每场面试各有 profile，掌握度应看用户全部历史。

    同一 skill 取最近评估的 level/confidence/trend（last_assessed_at 优先，
    updated_at 兜底 tie-break），样本与严重错误跨场次累计。
    """
    if user_id is None:
        return {}
    states = db.scalars(
        select(CandidateKnowledgeState).where(CandidateKnowledgeState.user_id == user_id)
    ).all()
    sessions = db.scalars(
        select(InterviewSession)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.created_at.asc(), InterviewSession.id.asc())
    ).all()
    ordinal = {session.id: index + 1 for index, session in enumerate(sessions)}
    by_skill: dict[str, list[CandidateKnowledgeState]] = {}
    for state in states:
        by_skill.setdefault(state.skill_id, []).append(state)
    mastery: dict[str, dict] = {}
    for skill_id, skill_states in by_skill.items():
        latest = max(
            skill_states,
            key=lambda s: (
                s.last_assessed_at or s.updated_at,
                s.updated_at,
                s.id,
            ),
        )
        mastery[skill_id] = {
            "level": latest.current_level,
            "sample_count": sum(s.valid_sample_count for s in skill_states),
            "trend": latest.trend,
            "confidence": latest.confidence,
            "last_assessed_at": (
                latest.last_assessed_at.isoformat() if latest.last_assessed_at else None
            ),
            "session_ordinal": ordinal.get(latest.last_session_id or ""),
        }
    return mastery


def _studied_skill_ids(db: Session, user_id: str | None) -> set[str]:
    if user_id is None:
        return set()
    rows = db.scalars(
        select(SkillStudyLog.skill_id).where(SkillStudyLog.user_id == user_id)
    )
    return set(rows)


def list_skills(db: Session) -> list[dict]:
    ensure_skill_wiki_seeds(db)
    profile = _local_profile(db)
    mastery = _mastery_by_skill(db, profile.user_id if profile else None)
    studied = _studied_skill_ids(db, profile.user_id if profile else None)
    wikis = {w.skill_id: w for w in db.scalars(select(SkillWiki))}
    skills = []
    for catalog in db.scalars(
        select(SkillCatalog).where(SkillCatalog.is_active.is_(True)).order_by(SkillCatalog.id)
    ):
        state = mastery.get(catalog.id, {})
        skills.append(
            {
                "skill_id": catalog.id,
                "name": catalog.canonical_name,
                "category": catalog.category,
                "level": state.get("level"),
                "sample_count": state.get("sample_count", 0),
                "studied": catalog.id in studied,
                "has_deep_dive": wikis.get(catalog.id).has_deep_dive if catalog.id in wikis else False,
            }
        )
    return skills


def get_skill_detail(db: Session, skill_id: str) -> dict:
    ensure_skill_wiki_seeds(db)
    catalog = db.get(SkillCatalog, skill_id)
    if catalog is None:
        raise NotFoundError("skill not found")
    wiki = db.get(SkillWiki, skill_id)
    sections = json.loads(wiki.content_json or "{}") if wiki else {}
    profile = _local_profile(db)
    mastery = _mastery_by_skill(db, profile.user_id if profile else None).get(
        skill_id,
        {
            "level": None,
            "sample_count": 0,
            "trend": "insufficient_data",
            "confidence": 0.0,
            "last_assessed_at": None,
            "session_ordinal": None,
        },
    )
    studied = skill_id in _studied_skill_ids(db, profile.user_id if profile else None)

    # 相关题目（题库平行题）与我最近一次的回答（供个性化学习）
    templates = QUESTION_TEMPLATES.get(skill_id, ())
    related_questions = [
        {"prompt": template.prompt, "template_id": template.template_id}
        for template in templates
    ]
    community_questions = [
        {"id": row.id, "text": row.text, "dup_count": row.dup_count}
        for row in db.scalars(
            select(CommunityQuestion)
            .where(CommunityQuestion.knowledge_point_slug == skill_id)
            .order_by(CommunityQuestion.dup_count.desc())
            .limit(8)
        ).all()
    ]
    recent_answer = None
    if profile is not None:
        answer_row = db.scalar(
            select(AnswerAttempt)
            .join(InterviewQuestion, AnswerAttempt.question_id == InterviewQuestion.id)
            .where(
                InterviewQuestion.knowledge_point_id == skill_id,
                AnswerAttempt.status.in_(("submitted", "explicit_unknown")),
            )
            .order_by(AnswerAttempt.created_at.desc())
        )
        if answer_row is not None and answer_row.status == "submitted":
            run = db.scalar(
                select(AssessmentRun.commentary)
                .where(AssessmentRun.answer_id == answer_row.id)
                .order_by(AssessmentRun.attempt_number.desc(), AssessmentRun.created_at.desc())
                .limit(1)
            )
            recent_answer = {
                "answer_text": answer_row.answer_text,
                "commentary": run,
            }

    return {
        "skill_id": skill_id,
        "name": catalog.canonical_name,
        "category": catalog.category,
        "sections": sections,
        "has_deep_dive": wiki.has_deep_dive if wiki else False,
        "mastery": mastery,
        "studied": studied,
        "related_questions": related_questions,
        "community_questions": community_questions,
        "recent_answer": recent_answer,
    }


def mark_studied(db: Session, skill_id: str, source: str) -> dict:
    catalog = db.get(SkillCatalog, skill_id)
    if catalog is None:
        raise NotFoundError("skill not found")
    profile = _local_profile(db)
    db.add(
        SkillStudyLog(
            id=str(uuid4()),
            user_id=profile.user_id if profile else "local-user",
            skill_id=skill_id,
            source=source,
            studied_at=utc_now(),
        )
    )
    db.commit()
    return {"skill_id": skill_id, "studied": True}


def generate_deep_dive(db: Session, skill_id: str, provider) -> dict:
    if provider is None or not hasattr(provider, "generate_skill_wiki"):
        from .providers import AssessmentProviderError

        raise AssessmentProviderError("provider_not_configured", "深讲生成服务尚未配置")
    detail = get_skill_detail(db, skill_id)
    sections = detail["sections"]
    payload = {
        "name": detail["name"],
        "definition": sections.get("definition", ""),
        "key_points": sections.get("key_points", []),
        "signals": [
            template.prompt for template in QUESTION_TEMPLATES.get(skill_id, ())
        ],
        "recent_answer": (detail.get("recent_answer") or {}).get("answer_text"),
        "recent_commentary": (detail.get("recent_answer") or {}).get("commentary"),
    }
    deep_dive = provider.generate_skill_wiki(payload)
    wiki = db.get(SkillWiki, skill_id)
    if wiki is None:
        from .skills_seed import SEED_CONTENT

        seed = SEED_CONTENT.get(skill_id, {})
        sections = {
            "definition": seed.get("definition", ""),
            "why": seed.get("why", ""),
            "key_points": [],
            "pitfalls": [],
            "examples": [],
        }
        wiki = SkillWiki(
            skill_id=skill_id,
            content_json=json.dumps(sections, ensure_ascii=False),
            source="preset",
        )
        db.add(wiki)
    existing = json.loads(wiki.content_json or "{}")
    existing["deep_dive"] = deep_dive
    wiki.content_json = json.dumps(existing, ensure_ascii=False)
    wiki.has_deep_dive = True
    wiki.source = "generated"
    wiki.model_name = provider.model_name
    wiki.prompt_version = WIKI_PROMPT_VERSION
    wiki.updated_at = utc_now()
    db.commit()
    return {"skill_id": skill_id, "deep_dive": deep_dive, "has_deep_dive": True}
