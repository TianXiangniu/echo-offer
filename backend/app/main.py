from pathlib import Path

from fastapi import Depends, FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import (
    ANALYSIS_TIMEOUT_SECONDS,
    DEFAULT_DATABASE_URL,
    DEFAULT_UPLOAD_ROOT,
    MAX_RESUME_UPLOAD_BYTES,
    SILICONFLOW_API_KEY,
    SILICONFLOW_BASE_URL,
    SILICONFLOW_MODEL,
    WORKFLOW_VERSION,
)
from .database import create_database, get_db
from .providers import (
    ProjectAnalysisProvider,
    ProjectAnalysisProviderError,
    RuleBasedAssessmentProvider,
    SiliconFlowProjectAnalysisProvider,
)
from .question_bank import build_question_specs
from .resume_files import ResumeUploadError, read_upload_bytes
from .resume_parsers import ResumeParserError
from .schemas import (
    AnswerResponse,
    AnswerSubmission,
    AgentProjectAnalysisRequest,
    AgentProjectAnalysisResponseEnvelope,
    ProfileCreate,
    ProfileResponse,
    ResumeParseResponse,
    ReportResponse,
    SessionCreate,
    SessionCreateResponse,
    SessionView,
)
from .services import (
    ConflictError,
    InvalidAnswerError,
    NotFoundError,
    ResumeNotFoundError,
    ResumeOwnerConflictError,
    ProjectAnalysisError,
    analyze_resume_project,
    create_profile,
    create_session,
    get_report,
    get_session_view,
    parse_and_store_resume,
    submit_answer,
)


def create_app(
    database_url: str | None = None,
    upload_root: Path | None = None,
    project_analysis_provider: ProjectAnalysisProvider | None = None,
) -> FastAPI:
    app = FastAPI(title="Agent Echo API", version=WORKFLOW_VERSION)
    _, session_factory = create_database(database_url or DEFAULT_DATABASE_URL)
    app.state.session_factory = session_factory
    app.state.upload_root = upload_root or DEFAULT_UPLOAD_ROOT
    app.state.assessment_provider = RuleBasedAssessmentProvider()
    app.state.project_analysis_provider = project_analysis_provider or SiliconFlowProjectAnalysisProvider(
        api_key=SILICONFLOW_API_KEY,
        model=SILICONFLOW_MODEL,
        base_url=SILICONFLOW_BASE_URL,
        timeout_seconds=ANALYSIS_TIMEOUT_SECONDS,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
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

    @app.exception_handler(ResumeUploadError)
    async def handle_resume_upload_error(_, exc: ResumeUploadError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc), "code": exc.code},
        )

    @app.exception_handler(ResumeParserError)
    async def handle_resume_parser_error(_, exc: ResumeParserError):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "code": exc.code},
        )

    @app.exception_handler(ResumeNotFoundError)
    async def handle_resume_not_found(_, exc: ResumeNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "code": exc.code},
        )

    @app.exception_handler(ResumeOwnerConflictError)
    async def handle_resume_owner_conflict(_, exc: ResumeOwnerConflictError):
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": exc.code},
        )

    @app.exception_handler(ProjectAnalysisError)
    async def handle_project_analysis_error(_, exc: ProjectAnalysisError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc), "code": exc.code},
        )

    @app.exception_handler(ProjectAnalysisProviderError)
    async def handle_project_analysis_provider_error(_, exc: ProjectAnalysisProviderError):
        status_by_code = {
            "provider_not_configured": 503,
            "provider_timeout": 504,
            "provider_rate_limited": 429,
            "provider_unavailable": 503,
            "provider_auth_failed": 502,
            "provider_connection_failed": 502,
            "invalid_model_response": 502,
        }
        return JSONResponse(
            status_code=status_by_code.get(exc.code, 502),
            content={"detail": str(exc), "code": exc.code},
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "workflow_version": WORKFLOW_VERSION}

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
        "/api/resumes/{resume_id}/agent-project-analysis",
        response_model=AgentProjectAnalysisResponseEnvelope,
    )
    def analyze_project(
        resume_id: str,
        payload: AgentProjectAnalysisRequest,
        db: Session = Depends(get_db),
    ):
        return analyze_resume_project(
            db,
            app.state.project_analysis_provider,
            resume_id,
            payload.resume_text,
        )

    @app.post("/api/sessions", response_model=SessionCreateResponse)
    def session(payload: SessionCreate, db: Session = Depends(get_db)):
        return create_session(db, payload.profile_id, build_question_specs())

    @app.get("/api/sessions/{session_id}", response_model=SessionView)
    def session_view(session_id: str, db: Session = Depends(get_db)):
        return get_session_view(db, session_id)

    @app.post("/api/sessions/{session_id}/answers", response_model=AnswerResponse)
    def answer(
        session_id: str,
        payload: AnswerSubmission,
        db: Session = Depends(get_db),
    ):
        return submit_answer(db, session_id, payload, app.state.assessment_provider)

    @app.get("/api/sessions/{session_id}/report", response_model=ReportResponse)
    def report(session_id: str, db: Session = Depends(get_db)):
        return get_report(db, session_id)

    return app


app = create_app()
