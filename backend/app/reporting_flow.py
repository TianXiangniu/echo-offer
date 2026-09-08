from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import (
    AnswerAttempt,
    AssessmentRun,
    CandidateKnowledgeState,
    ensure_utc,
    CandidateProfile,
    InterviewFollowup,
    InterviewQuestion,
    InterviewReport,
    InterviewSession,
    InterviewTarget,
    LearningRecommendation,
    OperationJob,
    OperationJobEvent,
    ProfileSnapshot,
    ResumeProject,
    RoleSkillRequirement,
    RubricObservation,
    SkillCatalog,
    SkillStudyLog,
)
from .profile_insights import (
    build_today_plan,
    freshness_of,
    practice_effectiveness,
    question_angle_distribution,
    recent_answers_for_skill,
    studied_skill_ids,
    verifiable_count,
)
from .workflow_common import NotFoundError, _get_active_session, calculate_score_100, utc_now
from .interview_types import interview_type_from_mode

def _build_report_payload(
    db: Session,
    session_id: str,
    assessment_batch_id: str | None = None,
) -> dict:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise NotFoundError("session not found")
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.order)
        )
    )
    answers = list(db.scalars(select(AnswerAttempt).where(AnswerAttempt.session_id == session_id)))
    by_question = {question.id: question for question in questions}
    answered_followups: dict[str, list] = {}
    for followup in db.scalars(
        select(InterviewFollowup)
        .where(
            InterviewFollowup.session_id == session_id,
            InterviewFollowup.status == "answered",
        )
        .order_by(InterviewFollowup.round)
    ):
        answered_followups.setdefault(followup.question_id, []).append(followup)
    completed = len({answer.question_id for answer in answers})
    anchor_ids = {question.id for question in questions if question.is_anchor}
    anchor_answered = len({answer.question_id for answer in answers if answer.question_id in anchor_ids})
    answer_ids = [answer.id for answer in answers]
    run_query = (
        select(AssessmentRun)
        .where(AssessmentRun.answer_id.in_(answer_ids))
        .order_by(AssessmentRun.attempt_number, AssessmentRun.created_at)
    ) if answer_ids else None
    all_runs = list(db.scalars(run_query)) if run_query is not None else []
    latest_all_runs: dict[str, AssessmentRun] = {}
    for run in all_runs:
        latest_all_runs[run.answer_id] = run
    if assessment_batch_id:
        latest_runs: dict[str, AssessmentRun] = {}
        for run in all_runs:
            if run.assessment_batch_id == assessment_batch_id:
                latest_runs[run.answer_id] = run
        for answer_id, run in latest_all_runs.items():
            latest_runs.setdefault(answer_id, run)
    else:
        latest_runs = latest_all_runs

    status_counts = {status: 0 for status in ("pending", "valid", "invalid", "rejected")}
    for run in latest_runs.values():
        if run.status in status_counts:
            status_counts[run.status] += 1

    strengths = []
    gaps = []
    distribution = {str(level): 0 for level in range(5)}
    rubric_items = []
    report_observations = []
    completed_question_ids = {answer.question_id for answer in answers}
    expected_scored_question_ids = {
        answer.question_id for answer in answers if answer.status != "skipped"
    }
    question_scores: dict[str, float] = {}
    for answer in answers:
        run = latest_runs.get(answer.id)
        if run is not None:
            if run.status != "valid" or run.aggregate_level is None:
                continue
            evidence = db.scalar(
                select(RubricObservation)
                .where(
                    RubricObservation.assessment_run_id == run.id,
                    RubricObservation.validity == "valid",
                )
                .order_by(RubricObservation.confidence.desc())
            )
            valid_items = list(
                db.scalars(
                    select(RubricObservation)
                    .where(
                        RubricObservation.assessment_run_id == run.id,
                        RubricObservation.validity == "valid",
                    )
                    .order_by(RubricObservation.rubric_id)
                )
            )
            round_followups = answered_followups.get(answer.question_id) or []
            rubric_items.extend(
                {
                    "question_id": answer.question_id,
                    "plan_node_id": run.plan_node_id,
                    "knowledge_point_id": by_question[answer.question_id].knowledge_point_id,
                    "rubric_id": item.rubric_id,
                    "level": item.level,
                    "confidence": item.confidence,
                    "evidence": item.quoted_text,
                    "commentary": run.commentary or "",
                    "followup_question": chr(10).join(
                        f"追问{index}：{f.question_text}"
                        for index, f in enumerate(round_followups, start=1)
                    ),
                    "followup_answer": chr(10).join(
                        (f.answer_text or "") for f in round_followups
                    ),
                }
                for item in valid_items
            )
            question_scores[answer.question_id] = round(
                sum(item.level for item in valid_items) / len(valid_items) / 4 * 100,
                2,
            ) if valid_items else round(run.aggregate_level / 4 * 100, 2)
            report_observations.append(
                {
                    "question_id": answer.question_id,
                    "plan_node_id": run.plan_node_id,
                    "level": run.aggregate_level,
                    "confidence": run.aggregate_confidence or 0.0,
                    "evidence": evidence.quoted_text if evidence else answer.answer_text,
                }
            )

    for observation in report_observations:
        distribution[str(observation["level"])] += 1
        item = {
            "knowledge_point_id": by_question[observation["question_id"]].knowledge_point_id,
            "plan_node_id": observation["plan_node_id"],
            "level": observation["level"],
            "confidence": observation["confidence"],
            "evidence": observation["evidence"],
        }
        if observation["level"] >= 3:
            strengths.append(item)
        else:
            gaps.append(item)
    strengths.sort(key=lambda item: item["level"], reverse=True)
    gaps.sort(key=lambda item: item["level"])
    average_confidence = round(
        sum(observation["confidence"] for observation in report_observations)
        / len(report_observations),
        2,
    ) if report_observations else 0.0
    evaluators = {run.evaluator for run in latest_runs.values()}
    if not evaluators and report_observations:
        evaluators.add("alpha-local-rule-v1")
    evaluator = next(iter(evaluators)) if len(evaluators) == 1 else "mixed"
    score_100 = calculate_score_100(
        question_scores,
        total_questions=len(questions),
        completed_question_ids=completed_question_ids,
        expected_scored_question_ids=expected_scored_question_ids,
    )
    # 完整问答回看：当时的题目、完整回答、追问与回答，按题号排列
    return {
        "session_id": session_id,
        "interview_type": interview_type_from_mode(session.mode),
        "completion": {"completed": completed, "total": len(questions)},
        "coverage": round(completed / len(questions), 3) if questions else 0.0,
        "anchor_coverage": {"answered": anchor_answered, "total": len(anchor_ids)},
        "strengths": strengths[:3],
        "gaps": gaps[:3],
        "level_distribution": distribution,
        "valid_evidence_count": len(report_observations),
        "confidence": average_confidence,
        "evaluator": evaluator,
        "score_100": score_100,
        "assessment_status_counts": status_counts,
        "rubric_items": rubric_items,
        "transcript": _build_transcript(db, session_id),
    }


def _build_transcript(db: Session, session_id: str) -> list[dict]:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise NotFoundError("session not found")
    questions = list(
        db.scalars(
            select(InterviewQuestion)
            .where(InterviewQuestion.session_id == session_id)
            .order_by(InterviewQuestion.order)
        )
    )
    answers = list(db.scalars(select(AnswerAttempt).where(AnswerAttempt.session_id == session_id)))
    answered_followups: dict[str, list] = {}
    for followup in db.scalars(
        select(InterviewFollowup)
        .where(
            InterviewFollowup.session_id == session_id,
            InterviewFollowup.status == "answered",
        )
        .order_by(InterviewFollowup.round)
    ):
        answered_followups.setdefault(followup.question_id, []).append(followup)
    answers_by_question: dict[str, AnswerAttempt] = {}
    for answer in answers:
        answers_by_question.setdefault(answer.question_id, answer)
    latest_run_by_question: dict[str, AssessmentRun | None] = {}
    for answer in answers:
        latest_run_by_question[answer.question_id] = db.scalar(
            select(AssessmentRun)
            .where(AssessmentRun.answer_id == answer.id)
            .order_by(AssessmentRun.attempt_number.desc(), AssessmentRun.created_at.desc())
        )
    transcript = []
    for question in questions:
        answer = answers_by_question.get(question.id)
        followups = answered_followups.get(question.id) or []
        run = latest_run_by_question.get(question.id)
        transcript.append(
            {
                "order": question.order,
                "category": question.category,
                "prompt": question.prompt,
                "knowledge_point_id": question.knowledge_point_id,
                "plan_node_id": run.plan_node_id if run else None,
                "status": answer.status if answer else "unanswered",
                "answer_text": answer.answer_text if answer else "",
                "followups": [
                    {
                        "question_text": followup.question_text,
                        "answer_text": followup.answer_text or "",
                    }
                    for followup in followups
                ],
                "level": run.aggregate_level if run else None,
                "commentary": (run.commentary if run else "") or "",
            }
        )
    return transcript


def persist_interview_report(
    db: Session,
    session_id: str,
    *,
    assessment_batch_id: str | None = None,
    status: str = "ready",
    commit: bool = True,
) -> InterviewReport:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise NotFoundError("session not found")
    latest_version = db.scalar(
        select(func.max(InterviewReport.version)).where(
            InterviewReport.session_id == session_id
        )
    )
    report_payload = _build_report_payload(
        db,
        session_id,
        assessment_batch_id=assessment_batch_id,
    )
    latest_run = db.scalar(
        select(AssessmentRun)
        .where(
            or_(
                AssessmentRun.assessment_batch_id == assessment_batch_id,
                AssessmentRun.batch_id == assessment_batch_id,
            )
        )
        .order_by(AssessmentRun.created_at.desc())
    ) if assessment_batch_id else None
    report = InterviewReport(
        id=str(uuid4()),
        session_id=session_id,
        assessment_run_id=latest_run.id if latest_run else None,
        assessment_batch_id=assessment_batch_id,
        version=(latest_version or 0) + 1,
        status=status,
        report_json=json.dumps(report_payload, ensure_ascii=False, sort_keys=True),
    )
    db.add(report)
    db.flush()
    session.current_report_id = report.id
    if latest_run is not None:
        session.current_assessment_run_id = latest_run.id
    session.current_assessment_batch_id = assessment_batch_id
    if commit:
        db.commit()
    return report


def get_persisted_report(db: Session, session_id: str) -> dict | None:
    report = db.scalar(
        select(InterviewReport)
        .where(
            InterviewReport.session_id == session_id,
            InterviewReport.status.in_(("ready", "partial")),
        )
        .order_by(InterviewReport.version.desc())
    )
    if report is None:
        return None
    return json.loads(report.report_json)


def get_report(db: Session, session_id: str) -> dict:
    session = _get_active_session(db, session_id)
    payload = get_persisted_report(db, session_id) or _build_report_payload(db, session_id)
    payload.setdefault("interview_type", interview_type_from_mode(session.mode))
    # transcript 实时构建：存量报告（存库 JSON）同样能回看完整问答
    payload["transcript"] = _build_transcript(db, session_id)
    return payload

def archive_interview(db: Session, session_id: str) -> None:
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    session.archived_at = utc_now()
    db.commit()


def list_interview_history(db: Session) -> list[dict]:
    sessions = list(
        db.scalars(
            select(InterviewSession)
            .where(InterviewSession.archived_at.is_(None))
            .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        )
    )
    history = []
    for session in sessions:
        question_count = db.scalar(
            select(func.count(InterviewQuestion.id)).where(
                InterviewQuestion.session_id == session.id
            )
        ) or 0
        answered_count = db.scalar(
            select(func.count(func.distinct(AnswerAttempt.question_id))).where(
                AnswerAttempt.session_id == session.id
            )
        ) or 0
        report = db.scalar(
            select(InterviewReport)
            .where(InterviewReport.session_id == session.id)
            .order_by(InterviewReport.version.desc())
        )
        job = db.scalar(
            select(OperationJob)
            .where(OperationJob.session_id == session.id)
            .order_by(OperationJob.created_at.desc(), OperationJob.id.desc())
        )
        target = db.get(InterviewTarget, session.target_id)
        project = db.get(ResumeProject, session.resume_project_id) if session.resume_project_id else None
        report_payload = json.loads(report.report_json) if report else None
        history.append(
            {
                "session_id": session.id,
                "status": session.status,
                "interview_type": interview_type_from_mode(session.mode),
                "profile_id": session.profile_id,
                "project_name": project.project_name if project else None,
                "direction": target.direction if target else None,
                "target_title": target.target_title if target else None,
                "completed": answered_count,
                "total": question_count,
                "score_100": report_payload.get("score_100") if report_payload else None,
                "report_status": report.status if report else None,
                "analysis_status": job.status if job else None,
                "strength_count": len(report_payload["strengths"]) if report_payload else None,
                "gap_count": len(report_payload["gaps"]) if report_payload else None,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
        )
    return history

def _recommendation_response(db: Session, recommendation: LearningRecommendation) -> dict:
    skill = db.get(SkillCatalog, recommendation.skill_id)
    profile = db.get(CandidateProfile, recommendation.profile_id)
    state = db.scalar(
        select(CandidateKnowledgeState).where(
            CandidateKnowledgeState.profile_id == recommendation.profile_id,
            CandidateKnowledgeState.skill_id == recommendation.skill_id,
        )
    )
    source = _find_recommendation_source(
        db,
        skill_id=recommendation.skill_id,
        preferred_session_id=state.last_session_id if state else None,
    )
    verification_ready = False
    if recommendation.practice_completed_at is not None:
        practice_at = ensure_utc(recommendation.practice_completed_at)
        verification_ready = utc_now() >= practice_at + timedelta(days=3)
    return {
        "id": recommendation.id,
        "skill_id": recommendation.skill_id,
        "skill_name": skill.canonical_name if skill else recommendation.skill_id,
        "priority": recommendation.priority,
        "reason": recommendation.reason,
        "actions": json.loads(recommendation.actions_json),
        "success_criteria": json.loads(recommendation.success_criteria_json),
        "status": recommendation.status,
        "recommended_review_at": recommendation.recommended_review_at,
        "practice_completed_at": recommendation.practice_completed_at,
        "verification_ready": verification_ready,
        "level": state.current_level if state else None,
        "studied": bool(
            profile
            and db.scalar(
                select(SkillStudyLog.skill_id).where(
                    SkillStudyLog.user_id == profile.user_id,
                    SkillStudyLog.skill_id == recommendation.skill_id,
                )
            )
        ),
        "last_assessed_at": (
            state.last_assessed_at.isoformat() if state and state.last_assessed_at else None
        ),
        **source,
    }


def _empty_recommendation_source() -> dict[str, object | None]:
    return {
        "source_session_id": None,
        "source_question_id": None,
        "source_question": None,
        "source_answer_excerpt": None,
        "source_level": None,
        "is_unknown": False,
    }


def _find_recommendation_source(
    db: Session,
    *,
    skill_id: str,
    preferred_session_id: str | None,
) -> dict[str, object | None]:
    empty = _empty_recommendation_source()
    if not preferred_session_id:
        return empty
    session = db.get(InterviewSession, preferred_session_id)
    if session is None:
        return empty

    candidates = []
    questions = db.scalars(
        select(InterviewQuestion)
        .where(
            InterviewQuestion.session_id == session.id,
            InterviewQuestion.knowledge_point_id == skill_id,
        )
        .order_by(InterviewQuestion.order.asc(), InterviewQuestion.id.asc())
    )
    for question in questions:
        answer = db.scalar(
            select(AnswerAttempt)
            .where(
                AnswerAttempt.session_id == session.id,
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
            .order_by(
                AssessmentRun.attempt_number.desc(),
                AssessmentRun.created_at.desc(),
                AssessmentRun.id.desc(),
            )
        )
        if run is None or run.status != "valid" or run.aggregate_level is None:
            continue
        candidates.append(
            (run.aggregate_level, question.order, question.id, question, answer, run)
        )

    if not candidates:
        return empty
    _, _, _, question, answer, run = min(candidates, key=lambda item: item[:3])
    is_unknown = answer.status == "explicit_unknown"
    return {
        "source_session_id": None if session.archived_at is not None else session.id,
        "source_question_id": question.id,
        "source_question": question.prompt,
        "source_answer_excerpt": None if is_unknown else answer.answer_text[:240],
        "source_level": run.aggregate_level,
        "is_unknown": is_unknown,
    }


def _days_since_local(value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, (utc_now() - ensure_utc(value)).days)


def get_profile_summary(db: Session, profile_id: str) -> dict:
    profile = db.get(CandidateProfile, profile_id)
    if profile is None:
        raise NotFoundError("profile not found")
    states = list(
        db.scalars(
            select(CandidateKnowledgeState)
            .where(CandidateKnowledgeState.profile_id == profile.id)
            .order_by(CandidateKnowledgeState.current_level.asc())
        )
    )
    # 最近 5 个快照（旧→新）提供每个技能的等级轨迹，供前端画趋势
    recent_snapshots = list(
        db.scalars(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.profile_id == profile.id)
            .order_by(ProfileSnapshot.version.desc())
            .limit(5)
        )
    )
    recent_snapshots.reverse()
    snapshot_levels: dict[str, list[int]] = {}
    for snapshot in recent_snapshots:
        skills_in_snapshot = json.loads(snapshot.profile_json).get("skills", [])
        for item in skills_in_snapshot:
            if isinstance(item.get("level"), int):
                snapshot_levels.setdefault(item["skill_id"], []).append(item["level"])
    studied = studied_skill_ids(db, profile.user_id)
    skills = []
    for state in states:
        skill = db.get(SkillCatalog, state.skill_id)
        requirement = db.scalar(
            select(RoleSkillRequirement).where(
                RoleSkillRequirement.direction == profile.direction,
                RoleSkillRequirement.level == profile.level,
                RoleSkillRequirement.skill_id == state.skill_id,
            )
        )
        trajectory = snapshot_levels.get(state.skill_id, [])
        if trajectory and trajectory[-1] != state.current_level:
            trajectory = trajectory + [state.current_level]
        elif not trajectory:
            trajectory = [state.current_level]
        fresh = freshness_of(state.last_assessed_at)
        skills.append(
            {
                "skill_id": state.skill_id,
                "skill_name": skill.canonical_name if skill else state.skill_id,
                "category": skill.category if skill else "其他",
                "level": state.current_level,
                "confidence": state.confidence,
                "sample_count": state.valid_sample_count,
                "trend": state.trend,
                "target_level": requirement.target_level if requirement else None,
                "last_session_id": state.last_session_id,
                "recent_levels": trajectory[-5:],
                "studied": state.skill_id in studied,
                "freshness": fresh,
                "days_since": _days_since_local(state.last_assessed_at),
                "recent_answers": recent_answers_for_skill(db, profile.id, state.skill_id),
            }
        )
    # 最近一场的变化：最新快照与上一份的差异（只保留有升降的技能）
    recent_changes = []
    if len(recent_snapshots) >= 2:
        def _levels(snapshot: ProfileSnapshot) -> dict[str, int]:
            return {
                item["skill_id"]: item["level"]
                for item in json.loads(snapshot.profile_json).get("skills", [])
                if isinstance(item.get("level"), int)
            }

        previous_levels = _levels(recent_snapshots[-2])
        current_levels = _levels(recent_snapshots[-1])
        names = {s["skill_id"]: s["skill_name"] for s in skills}
        for skill_id, level in current_levels.items():
            previous = previous_levels.get(skill_id)
            if previous is not None and level != previous:
                recent_changes.append(
                    {
                        "skill_id": skill_id,
                        "skill_name": names.get(skill_id, skill_id),
                        "delta": level - previous,
                    }
                )
    recommendations = []
    if profile.current_snapshot_id:
        recommendations = [
            _recommendation_response(db, item)
            for item in db.scalars(
                select(LearningRecommendation)
                .where(
                    LearningRecommendation.profile_id == profile.id,
                    LearningRecommendation.profile_snapshot_id == profile.current_snapshot_id,
                )
            )
        ]
        priority_order = {"high": 0, "medium": 1, "insufficient_data": 2, "low": 3}
        recommendations.sort(key=lambda item: priority_order.get(item["priority"], 4))
    latest_state = max(
        (state for state in states if state.last_assessed_at is not None),
        key=lambda state: state.last_assessed_at,
        default=None,
    )
    last_session_id = latest_state.last_session_id if latest_state else None
    levels = [s["level"] for s in skills]
    targets = [s["target_level"] for s in skills if s["target_level"] is not None]
    # 衰减 readiness：生疏（>10 天未练）技能的等级按 0.8 折算——准备度是活的
    decayed = [
        level * 0.8 if s["freshness"] == "stale" else level
        for s, level in zip(skills, levels)
    ]
    target = db.scalars(
        select(InterviewTarget).where(InterviewTarget.user_id == profile.user_id)
    ).first()
    return {
        "profile_id": profile.id,
        "direction": profile.direction,
        "level": profile.level,
        "target_title": profile.target_title,
        "summary": profile.summary,
        "last_session_id": last_session_id,
        "skills": skills,
        "recommendations": recommendations,
        "recent_changes": recent_changes,
        "readiness": round(sum(decayed) / len(decayed) / 4 * 100) if decayed else None,
        "avg_target": round(sum(targets) / len(targets), 1) if targets else None,
        "question_angles": question_angle_distribution(db, profile.id),
        "practice_effectiveness": practice_effectiveness(db, profile.id),
        "verifiable_count": verifiable_count(db, profile.id),
        "target_date": target.target_date if target else None,
        "today_plan": build_today_plan(db, profile, states, target.target_date if target else None),
        "updated_at": profile.updated_at,
    }

def get_profile_history(db: Session, profile_id: str) -> list[dict]:
    profile = db.get(CandidateProfile, profile_id)
    if profile is None:
        raise NotFoundError("profile not found")
    snapshots = list(
        db.scalars(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.profile_id == profile_id)
            .order_by(ProfileSnapshot.version.desc())
        )
    )
    return [
        {
            "id": snapshot.id,
            "profile_id": snapshot.profile_id,
            "source_session_id": snapshot.source_session_id,
            "version": snapshot.version,
            "profile": json.loads(snapshot.profile_json),
            "created_at": snapshot.created_at,
        }
        for snapshot in snapshots
    ]


def get_operation_job(db: Session, job_id: str) -> dict:
    job = db.get(OperationJob, job_id)
    if job is None:
        raise NotFoundError("operation job not found")
    events = list(
        db.scalars(
            select(OperationJobEvent)
            .where(OperationJobEvent.job_id == job.id)
            .order_by(OperationJobEvent.sequence)
        )
    )
    return {
        "id": job.id,
        "operation_kind": job.operation_kind,
        "session_id": job.session_id,
        "assessment_batch_id": job.assessment_batch_id,
        "status": job.status,
        "progress": job.progress,
        "current_stage": job.current_stage,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "progress": event.progress,
                "message": event.message,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


def update_recommendation_status(
    db: Session,
    recommendation_id: str,
    status: str,
) -> dict:
    if status not in {"recommended", "in_progress", "completed", "dismissed"}:
        raise InvalidAnswerError("unsupported recommendation status")
    recommendation = db.get(LearningRecommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("recommendation not found")
    recommendation.status = status
    db.commit()
    return _recommendation_response(db, recommendation)
