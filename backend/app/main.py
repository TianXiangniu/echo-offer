from pathlib import Path
from contextlib import asynccontextmanager, contextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import (
    DEFAULT_DATABASE_URL,
    DEFAULT_UPLOAD_ROOT,
    MAX_RESUME_UPLOAD_BYTES,
    WORKFLOW_VERSION,
)
from .database import create_database, get_db
from .model_settings import (
    ModelSettingsError,
    load_model_settings,
    public_model_settings,
    save_model_settings,
)
from .providers import (
    AssessmentProvider,
    AssessmentProviderError,
    SiliconFlowAssessmentProvider,
    SiliconFlowFollowupProvider,
    ProjectAnalysisProvider,
    ProjectAnalysisProviderError,
    SiliconFlowProjectAnalysisProvider,
    probe_model_connection,
)
from .models import InterviewTarget, LlmCallTrace
from .resume_files import ResumeUploadError, read_upload_bytes
from .resume_parsers import ResumeParserError
from .schemas import (
    CommunityQuestionCreate,
    TargetDateUpdate,
    AnswerResponse,
    AnswerSubmission,
    AssessmentBatchResponse,
    AgentProjectAnalysisRequest,
    AgentProjectAnalysisResponseEnvelope,
    ProjectCandidatesResponse,
    ProjectCandidatesRequest,
    FollowupAnswerResponse,
    FollowupAnswerSubmission,
    DialogAnswerSubmission,
    FollowupDecisionResponse,
    OpenDrillRequest,
    SkillDetailResponse,
    SkillListResponse,
    SkillStudyResponse,
    PracticeFeedbackResponse,
    PracticeSessionResponse,
    ProfileCreate,
    ProfileSnapshotResponse,
    ProfileSummaryResponse,
    RecommendationStatusUpdate,
    ProfileResponse,
    ResumeParseResponse,
    ReportResponse,
    InterviewHistoryItem,
    LearningRecommendationResponse,
    OperationJobResponse,
    ModelConnectionTestResponse,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    SessionCreate,
    SessionCreateResponse,
    SessionView,
    GraphAnswerSubmission,
)
from .interview_flow import (
    create_foundation_session,
    create_session,
    get_session_view,
    submit_answer,
)
from .interview_graph_projection import build_projected_interview_graph
from .interview_graph_api import graph_events, graph_state, resume_graph, start_graph
from .interview_graph_runtime import close_checkpointer, create_checkpointer
from .interview_agents import SiliconFlowInterviewAgents
from .dialog_flow import (
    finish_dialog_early,
    handle_dialog_answer,
    skip_wrap_up,
)
from .followup_flow import decide_followup, submit_followup_answer
from .feedback_flow import generate_feedback
from .practice_flow import create_drill_session, create_open_drill, create_verification_session
from .skills_flow import generate_deep_dive, get_skill_detail, list_skills, mark_studied
from .skills_seed import ensure_skill_wiki_seeds
from .reporting_flow import (
    archive_interview,
    get_operation_job,
    get_profile_history,
    get_profile_summary,
    get_report,
    list_interview_history,
    update_recommendation_status,
)
from .resume_intake import (
    analyze_resume_project,
    analyze_resume_project_candidates,
    create_profile,
    parse_and_store_resume,
    stream_resume_project_analysis,
)
from .assessment_flow import assess_session
from .workflow_common import (
    ConflictError,
    InvalidAnswerError,
    NotFoundError,
    ProjectAnalysisError,
    ResumeNotFoundError,
    ResumeOwnerConflictError,
)
from .llm_observability import capture_model_calls, record_model_calls

# provider 错误码 → HTTP 状态；未列出的码一律 502
PROVIDER_ERROR_STATUS = {
    "provider_not_configured": 503,
    "provider_timeout": 504,
    "provider_rate_limited": 429,
    "provider_unavailable": 503,
    "provider_auth_failed": 502,
    "provider_connection_failed": 502,
    "invalid_model_response": 502,
}


def build_model_providers(settings):
    return (
        SiliconFlowAssessmentProvider(
            api_key=settings.api_key,
            model=settings.assessment_model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        ),
        SiliconFlowProjectAnalysisProvider(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        ),
        SiliconFlowFollowupProvider(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            temperature=settings.temperature,
        ),
    )


def create_app(
    database_url: str | None = None,
    upload_root: Path | None = None,
    project_analysis_provider: ProjectAnalysisProvider | None = None,
    assessment_provider: AssessmentProvider | None = None,
    followup_provider=None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        close_checkpointer(application.state.interview_graph_checkpointer)

    app = FastAPI(title="Agent Echo API", version=WORKFLOW_VERSION, lifespan=lifespan)
    engine, session_factory = create_database(database_url or DEFAULT_DATABASE_URL)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.interview_graph_builder = build_projected_interview_graph
    app.state.upload_root = upload_root or DEFAULT_UPLOAD_ROOT
    with session_factory() as settings_db:
        app.state.model_settings = load_model_settings(settings_db)
    app.state.interview_graph_agents = SiliconFlowInterviewAgents(app.state.model_settings)
    app.state.interview_graph_checkpointer = create_checkpointer(
        str(app.state.upload_root.parent / "interview-graph-checkpoints.sqlite")
    )

    with session_factory() as seed_db:
        ensure_skill_wiki_seeds(seed_db)
    default_followup = None
    if assessment_provider is None or project_analysis_provider is None:
        default_assessment, default_project, default_followup = build_model_providers(
            app.state.model_settings
        )
        app.state.assessment_provider = assessment_provider or default_assessment
        app.state.project_analysis_provider = project_analysis_provider or default_project
    else:
        app.state.assessment_provider = assessment_provider
        app.state.project_analysis_provider = project_analysis_provider
    app.state.followup_provider = (
        followup_provider
        or (
            assessment_provider
            if assessment_provider is not None and hasattr(assessment_provider, "decide_followup")
            else None
        )
        or default_followup
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def handle_conflict(_, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidAnswerError)
    async def handle_invalid_answer(_, exc: InvalidAnswerError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def _register_code_error(exc_class, status):
        def handler(_, exc):
            return JSONResponse(status_code=status, content={"detail": str(exc), "code": exc.code})
        app.add_exception_handler(exc_class, handler)

    def _register_exc_status_error(exc_class):
        def handler(_, exc):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": str(exc), "code": exc.code},
            )
        app.add_exception_handler(exc_class, handler)

    _register_code_error(ResumeParserError, 422)
    _register_code_error(ResumeNotFoundError, 404)
    _register_code_error(ResumeOwnerConflictError, 409)
    _register_code_error(ModelSettingsError, 422)
    _register_exc_status_error(ResumeUploadError)
    _register_exc_status_error(ProjectAnalysisError)

    def _register_provider_error(exc_class):
        def handler(_, exc):
            return JSONResponse(
                status_code=PROVIDER_ERROR_STATUS.get(exc.code, 502),
                content={"detail": str(exc), "code": exc.code},
            )
        app.add_exception_handler(exc_class, handler)

    @contextmanager
    def observed_model_call(db: Session, session_id: str | None = None):
        with capture_model_calls(str(uuid4())) as capture:
            try:
                yield
            finally:
                if capture.records:
                    record_model_calls(
                        db, capture.records, pricing=app.state.model_settings.pricing,
                        session_id=session_id, operation_job_id=None,
                    )
                    db.commit()

    _register_provider_error(ProjectAnalysisProviderError)
    _register_provider_error(AssessmentProviderError)

    @app.get("/health")
    def health():
        try:
            with app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            database_status = "connected"
        except Exception:
            database_status = "unavailable"
        return {
            "status": "ok" if database_status == "connected" else "degraded",
            "workflow_version": WORKFLOW_VERSION,
            "database": database_status,
        }

    @app.get("/api/settings/model", response_model=ModelSettingsResponse)
    def model_settings(db: Session = Depends(get_db)):
        settings = load_model_settings(db)
        app.state.model_settings = settings
        return public_model_settings(settings)

    @app.put("/api/settings/model", response_model=ModelSettingsResponse)
    def update_model_settings(
        payload: ModelSettingsUpdate,
        db: Session = Depends(get_db),
    ):
        settings = save_model_settings(db, payload)
        next_assessment, next_project, next_followup = build_model_providers(settings)
        db.commit()
        app.state.model_settings = settings
        app.state.assessment_provider = next_assessment
        app.state.project_analysis_provider = next_project
        app.state.followup_provider = next_followup
        return public_model_settings(settings)

    @app.post(
        "/api/settings/model/test",
        response_model=ModelConnectionTestResponse,
    )
    def test_model_settings(db: Session = Depends(get_db)):
        settings = load_model_settings(db)
        app.state.model_settings = settings
        return probe_model_connection(settings)

    @app.post("/api/profile", response_model=ProfileResponse)
    def profile(payload: ProfileCreate, db: Session = Depends(get_db)):
        return create_profile(db, payload)

    @app.post("/api/resumes/parse", response_model=ResumeParseResponse)
    async def parse_resume(file: UploadFile, db: Session = Depends(get_db)):
        file_bytes = await read_upload_bytes(file, MAX_RESUME_UPLOAD_BYTES)
        return parse_and_store_resume(
            db,
            file_bytes=file_bytes,
            original_filename=file.filename or "",
            content_type=file.content_type,
            upload_root=app.state.upload_root,
        )

    @app.post(
        "/api/resumes/{resume_id}/agent-project-candidates",
        response_model=ProjectCandidatesResponse,
    )
    def analyze_project_candidates(
        resume_id: str,
        payload: ProjectCandidatesRequest,
        db: Session = Depends(get_db),
    ):
        with observed_model_call(db):
            return analyze_resume_project_candidates(db, app.state.project_analysis_provider, resume_id, payload.resume_text)

    @app.post(
        "/api/resumes/{resume_id}/agent-project-analysis",
        response_model=AgentProjectAnalysisResponseEnvelope,
    )
    def analyze_project(
        resume_id: str,
        payload: AgentProjectAnalysisRequest,
        db: Session = Depends(get_db),
    ):
        with observed_model_call(db):
            return analyze_resume_project(db, app.state.project_analysis_provider, resume_id, payload.resume_text, payload.selected_project_name)

    @app.post("/api/resumes/{resume_id}/agent-project-analysis/stream")
    async def analyze_project_stream(
        resume_id: str,
        payload: AgentProjectAnalysisRequest,
        db: Session = Depends(get_db),
    ):
        return StreamingResponse(
            stream_resume_project_analysis(
                db,
                app.state.project_analysis_provider,
                resume_id,
                payload.resume_text,
                payload.selected_project_name,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/sessions", response_model=SessionCreateResponse)
    def session(payload: SessionCreate, db: Session = Depends(get_db)):
        return create_session(db, payload.profile_id, mode=payload.mode)

    @app.post("/api/sessions/foundation", response_model=SessionCreateResponse)
    def foundation_session(db: Session = Depends(get_db)):
        return create_foundation_session(db)

    @app.post("/api/sessions/{session_id}/graph/start")
    def graph_start(session_id: str, db: Session = Depends(get_db)):
        with observed_model_call(db, session_id):
            return start_graph(
                db,
                session_id,
                graph_builder=app.state.interview_graph_builder,
                agents=app.state.interview_graph_agents,
                checkpointer=app.state.interview_graph_checkpointer,
                on_completed=lambda: assess_session(
                    db, session_id, app.state.assessment_provider
                ),
            )

    @app.post("/api/sessions/{session_id}/graph/resume")
    def graph_resume(
        session_id: str,
        payload: GraphAnswerSubmission,
        db: Session = Depends(get_db),
    ):
        with observed_model_call(db, session_id):
            return resume_graph(
                db,
                session_id,
                payload,
                graph_builder=app.state.interview_graph_builder,
                agents=app.state.interview_graph_agents,
                checkpointer=app.state.interview_graph_checkpointer,
                on_completed=lambda: assess_session(
                    db, session_id, app.state.assessment_provider
                ),
            )

    @app.get("/api/sessions/{session_id}/graph/state")
    def graph_state_view(session_id: str, db: Session = Depends(get_db)):
        return graph_state(
            db,
            session_id,
            graph_builder=app.state.interview_graph_builder,
            agents=app.state.interview_graph_agents,
            checkpointer=app.state.interview_graph_checkpointer,
        )

    @app.get("/api/sessions/{session_id}/graph/events")
    def graph_event_stream(session_id: str, db: Session = Depends(get_db)):
        return StreamingResponse(
            graph_events(db, session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/sessions/{session_id}/dialog/answer")
    def dialog_answer(
        session_id: str,
        payload: DialogAnswerSubmission,
        db: Session = Depends(get_db),
    ):
        return handle_dialog_answer(
            db, session_id, payload.text, app.state.followup_provider
        )

    @app.post("/api/sessions/{session_id}/dialog/finish")
    def dialog_finish(session_id: str, db: Session = Depends(get_db)):
        return finish_dialog_early(db, session_id)

    @app.post("/api/sessions/{session_id}/wrapup/skip")
    def wrapup_skip(session_id: str, db: Session = Depends(get_db)):
        return skip_wrap_up(db, session_id)

    @app.get("/api/interviews/history", response_model=list[InterviewHistoryItem])
    def interview_history(db: Session = Depends(get_db)):
        return list_interview_history(db)

    @app.get("/api/profiles/{profile_id}/summary", response_model=ProfileSummaryResponse)
    def profile_summary(profile_id: str, db: Session = Depends(get_db)):
        return get_profile_summary(db, profile_id)

    @app.get("/api/profiles/{profile_id}/history", response_model=list[ProfileSnapshotResponse])
    def profile_history(profile_id: str, db: Session = Depends(get_db)):
        return get_profile_history(db, profile_id)

    @app.patch(
        "/api/recommendations/{recommendation_id}",
        response_model=LearningRecommendationResponse,
    )
    def recommendation_status(
        recommendation_id: str,
        payload: RecommendationStatusUpdate,
        db: Session = Depends(get_db),
    ):
        return update_recommendation_status(db, recommendation_id, payload.status)

    @app.post(
        "/api/recommendations/{recommendation_id}/drill",
        response_model=PracticeSessionResponse,
    )
    def recommendation_drill(recommendation_id: str, db: Session = Depends(get_db)):
        return create_drill_session(db, recommendation_id)

    @app.post(
        "/api/recommendations/{recommendation_id}/verify",
        response_model=PracticeSessionResponse,
    )
    def recommendation_verify(recommendation_id: str, db: Session = Depends(get_db)):
        return create_verification_session(db, recommendation_id)

    @app.get("/api/skills", response_model=SkillListResponse)
    def skills_list(db: Session = Depends(get_db)):
        return {"skills": list_skills(db)}

    @app.get("/api/skills/{skill_id}", response_model=SkillDetailResponse)
    def skill_detail(skill_id: str, db: Session = Depends(get_db)):
        return get_skill_detail(db, skill_id)

    @app.post("/api/skills/{skill_id}/study", response_model=SkillStudyResponse)
    def skill_study(skill_id: str, db: Session = Depends(get_db)):
        return mark_studied(db, skill_id, source="skills_page")

    @app.post("/api/skills/{skill_id}/wiki/generate")
    def skill_wiki_generate(skill_id: str, db: Session = Depends(get_db)):
        return generate_deep_dive(db, skill_id, app.state.assessment_provider)

    @app.get("/api/community-questions")
    def community_questions(
        phase: str | None = None,
        knowledge_point: str | None = None,
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
    ):
        from sqlalchemy import func

        from .models import CommunityQuestion, SkillCatalog

        new_point_labels = {
            "new:llm_finetuning": "大模型微调",
            "new:cs_fundamentals": "计算机基础",
            "new:transformer_architecture": "Transformer 原理",
            "new:algorithm": "手撕算法",
            "new:agent_harness": "Agent Harness",
            "new:context_engineering": "上下文工程",
            "new:prompt_engineering": "提示词工程",
            "new:system_design": "系统设计",
            "new:llm_inference": "推理优化",
            "new:llm_infra": "训练基础设施",
            "new:llm_fundamentals": "大模型基础",
            "new:agent_planning": "任务规划",
            "new:agent_basics": "Agent 基础",
            "new:agent_fundamentals": "Agent 基础",
            "new:agent_skills": "Agent Skills",
            "new:agent_guardrails": "安全与护栏",
            "new:ai_coding": "AI Coding",
            "new:career_motivation": "职业动机",
            "new:hr_motivation": "职业动机",
            "new:hr_general": "HR 综合",
            "new:hr_onboarding": "入职意向",
            "new:code_coverage": "单测覆盖率",
            "new:unit_testing": "单元测试",
            "new:multimodal_llm": "多模态",
            "new:multimodal_architecture": "多模态",
            "new:information_extraction": "信息抽取",
            "new:long_text_generation": "长文本生成",
            "new:product_sense": "产品思维",
            "new:inference_optimization": "推理优化",
            "new:behavioral_motivation": "职业动机",
            "behavioral.failure_story": "失败与复盘",
            "behavioral.project_conflict": "协作与冲突",
        }
        skill_names = dict(
            db.execute(select(SkillCatalog.id, SkillCatalog.canonical_name)).all()
        )
        skill_ids = set(skill_names)

        def label(slug: str) -> str:
            return new_point_labels.get(slug) or skill_names.get(slug) or slug

        knowledge_point_counts = db.execute(
            select(CommunityQuestion.knowledge_point_slug, func.count())
            .group_by(CommunityQuestion.knowledge_point_slug)
        ).all()

        query = select(CommunityQuestion)
        if phase:
            query = query.where(CommunityQuestion.phase == phase)
        if knowledge_point:
            matching = {knowledge_point}
            matching |= {
                slug
                for slug, _ in knowledge_point_counts
                if label(slug) == knowledge_point
            }
            query = query.where(CommunityQuestion.knowledge_point_slug.in_(matching))
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(
            query.order_by(
                CommunityQuestion.dup_count.desc(),
                CommunityQuestion.created_at.desc(),
            ).limit(max(1, min(limit, 200))).offset(max(0, offset))
        ).all()
        phase_counts = db.execute(
            select(CommunityQuestion.phase, func.count()).group_by(CommunityQuestion.phase)
        ).all()

        label_counts: dict[str, int] = {}
        for slug, count in knowledge_point_counts:
            name = label(slug)
            label_counts[name] = label_counts.get(name, 0) + count
        knowledge_point_facets = [
            {"value": name, "count": count}
            for name, count in sorted(
                label_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        return {
            "total": total,
            "questions": [
                {
                    "id": row.id,
                    "text": row.text,
                    "phase": row.phase,
                    "knowledge_point": row.knowledge_point_slug,
                    "knowledge_point_label": label(row.knowledge_point_slug),
                    "linked_skill_id": (
                        row.knowledge_point_slug
                        if row.knowledge_point_slug in skill_ids
                        else None
                    ),
                    "note_url": row.note_url,
                    "dup_count": row.dup_count,
                }
                for row in rows
            ],
            "phases": [{"value": value, "count": count} for value, count in phase_counts],
            "knowledge_points": knowledge_point_facets,
        }

    @app.post("/api/community-questions")
    def add_community_question(payload: CommunityQuestionCreate, db: Session = Depends(get_db)):
        import hashlib
        import re as _re
        import uuid as _uuid

        from sqlalchemy import func

        from .models import CommunityQuestion

        text = payload.text.strip()
        knowledge_point = payload.knowledge_point.strip() or "未分类"
        normalized = _re.sub(r"[\s，。？?！!：:；;、\.·…\"“”‘’（）()\-—_`]", "", text)
        content_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        duplicate_count = db.scalar(
            select(func.count())
            .select_from(
                select(CommunityQuestion)
                .where(CommunityQuestion.content_hash == content_hash)
                .subquery()
            )
        )
        if duplicate_count:
            raise ConflictError("题库中已存在相同题目")

        row = CommunityQuestion(
            id=str(_uuid.uuid4()),
            text=text,
            phase=payload.phase,
            knowledge_point_slug=knowledge_point,
            note_url="",
            note_id="manual",
            dup_count=1,
            content_hash=content_hash,
        )
        db.add(row)
        db.commit()
        return {
            "id": row.id,
            "text": row.text,
            "phase": row.phase,
            "knowledge_point": row.knowledge_point_slug,
            "knowledge_point_label": row.knowledge_point_slug,
            "note_url": row.note_url,
            "dup_count": row.dup_count,
        }

    @app.delete("/api/community-questions/{question_id}")
    def remove_community_question(question_id: str, db: Session = Depends(get_db)):
        from .models import CommunityQuestion

        row = db.get(CommunityQuestion, question_id)
        if row is None:
            raise NotFoundError("community question not found")
        db.delete(row)
        db.commit()
        return {"deleted": question_id}

    @app.put("/api/profiles/{profile_id}/target-date")
    def set_target_date(profile_id: str, payload: TargetDateUpdate, db: Session = Depends(get_db)):
        from datetime import datetime, timezone as tz

        from .models import CandidateProfile

        profile_row = db.get(CandidateProfile, profile_id)
        if profile_row is None:
            raise NotFoundError("profile not found")
        target_row = db.scalars(
            select(InterviewTarget).where(InterviewTarget.user_id == profile_row.user_id)
        ).first()
        if target_row is None:
            raise NotFoundError("target not found")
        target_row.target_date = (
            datetime.strptime(payload.date, "%Y-%m-%d").replace(tzinfo=tz.utc)
            if payload.date
            else None
        )
        db.commit()
        return {
            "target_date": target_row.target_date.isoformat() if target_row.target_date else None
        }

    @app.post(
        "/api/practice/drill",
        response_model=PracticeSessionResponse,
    )
    def open_drill(payload: OpenDrillRequest, db: Session = Depends(get_db)):
        result = create_open_drill(db, payload.skill_id)
        return {
            "session_id": result["session_id"],
            "session_kind": result["session_kind"],
        }

    @app.get("/api/sessions/{session_id}", response_model=SessionView)
    def session_view(session_id: str, db: Session = Depends(get_db)):
        return get_session_view(db, session_id)

    @app.delete("/api/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str, db: Session = Depends(get_db)):
        archive_interview(db, session_id)
        return None

    @app.post("/api/sessions/{session_id}/answers", response_model=AnswerResponse)
    def answer(
        session_id: str,
        payload: AnswerSubmission,
        db: Session = Depends(get_db),
    ):
        return submit_answer(db, session_id, payload)

    @app.post(
        "/api/sessions/{session_id}/questions/{question_id}/followup/decide",
        response_model=FollowupDecisionResponse,
    )
    def followup_decide(
        session_id: str,
        question_id: str,
        db: Session = Depends(get_db),
    ):
        if not app.state.model_settings.followup_enabled:
            return {"followup": None}
        with observed_model_call(db, session_id):
            return decide_followup(
                db, session_id, question_id, app.state.followup_provider,
                persona=app.state.model_settings.persona,
            )

    @app.post(
        "/api/sessions/{session_id}/questions/{question_id}/followup/answer",
        response_model=FollowupAnswerResponse,
    )
    def followup_answer(
        session_id: str,
        question_id: str,
        payload: FollowupAnswerSubmission,
        db: Session = Depends(get_db),
    ):
        return submit_followup_answer(db, session_id, question_id, payload)

    @app.post(
        "/api/sessions/{session_id}/questions/{question_id}/feedback",
        response_model=PracticeFeedbackResponse,
    )
    def question_feedback(
        session_id: str,
        question_id: str,
        db: Session = Depends(get_db),
    ):
        if not app.state.model_settings.practice_feedback_enabled:
            return {"feedback": None}
        with observed_model_call(db, session_id):
            return generate_feedback(db, session_id, question_id, app.state.followup_provider)

    @app.post(
        "/api/sessions/{session_id}/assessment",
        response_model=AssessmentBatchResponse,
    )
    def assessment(session_id: str, db: Session = Depends(get_db)):
        with observed_model_call(db, session_id):
            return assess_session(db, session_id, app.state.assessment_provider)

    @app.get("/api/sessions/{session_id}/report", response_model=ReportResponse)
    def report(session_id: str, db: Session = Depends(get_db)):
        return get_report(db, session_id)

    @app.get("/api/jobs/{job_id}", response_model=OperationJobResponse)
    def operation_job(job_id: str, db: Session = Depends(get_db)):
        return get_operation_job(db, job_id)

    @app.get("/api/observability/summary")
    def observability_summary(session_id: str | None = None, db: Session = Depends(get_db)):
        query = select(LlmCallTrace)
        if session_id:
            query = query.where(LlmCallTrace.session_id == session_id)
        rows = list(db.scalars(query.order_by(LlmCallTrace.finished_at.desc()).limit(1000)))
        known_cost = sum((row.cost_cny or 0) for row in rows)
        return {
            "call_count": len(rows),
            "known_cost_cny": str(known_cost),
            "unpriced_call_count": sum(row.cost_cny is None for row in rows),
            "total_tokens": sum((row.total_tokens or 0) for row in rows),
            "success_rate": round(sum(row.status == "succeeded" for row in rows) / len(rows), 4) if rows else None,
            "average_latency_ms": round(sum(row.latency_ms for row in rows) / len(rows)) if rows else None,
            "items": [{
                "id": row.id, "trace_id": row.trace_id, "session_id": row.session_id,
                "call_kind": row.call_kind, "model_name": row.model_name, "status": row.status,
                "error_code": row.error_code, "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens, "total_tokens": row.total_tokens,
                "cost_cny": str(row.cost_cny) if row.cost_cny is not None else None,
                "latency_ms": row.latency_ms, "finished_at": row.finished_at,
            } for row in rows[:100]],
        }

    return app


app = create_app()
