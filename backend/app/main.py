from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import DEFAULT_DATABASE_URL, WORKFLOW_VERSION
from .database import create_database, get_db
from .providers import RuleBasedAssessmentProvider
from .question_bank import build_question_specs
from .schemas import (
    AnswerResponse,
    AnswerSubmission,
    ProfileCreate,
    ProfileResponse,
    ReportResponse,
    SessionCreate,
    SessionCreateResponse,
    SessionView,
)
from .services import (
    ConflictError,
    InvalidAnswerError,
    NotFoundError,
    create_profile,
    create_session,
    get_report,
    get_session_view,
    submit_answer,
)


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Agent Echo API", version=WORKFLOW_VERSION)
    _, session_factory = create_database(database_url or DEFAULT_DATABASE_URL)
    app.state.session_factory = session_factory
    app.state.assessment_provider = RuleBasedAssessmentProvider()
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

    @app.get("/health")
    def health():
        return {"status": "ok", "workflow_version": WORKFLOW_VERSION}

    @app.post("/api/profile", response_model=ProfileResponse)
    def profile(payload: ProfileCreate, db: Session = Depends(get_db)):
        return create_profile(db, payload)

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
