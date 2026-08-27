from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resume_text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResumeSource(Base):
    __tablename__ = "resume_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(260))
    file_size: Mapped[int] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(String(64))
    unit_count: Mapped[int] = mapped_column(Integer)
    extracted_text: Mapped[str] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(20), default="parsed")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResumeProject(Base):
    __tablename__ = "resume_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    project_name: Mapped[str] = mapped_column(String(200))
    background_goal: Mapped[str] = mapped_column(Text)
    tech_stack: Mapped[str] = mapped_column(Text)
    responsibilities: Mapped[str] = mapped_column(Text)
    core_solution: Mapped[str] = mapped_column(Text)
    engineering_challenges: Mapped[str] = mapped_column(Text)
    failure_improvements: Mapped[str] = mapped_column(Text)
    quantified_results: Mapped[str] = mapped_column(Text)
    project_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InterviewTarget(Base):
    __tablename__ = "interview_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    direction: Mapped[str] = mapped_column(String(80), default="agent_application_rag")
    level: Mapped[str] = mapped_column(String(80), default="one_to_three_years")
    language: Mapped[str] = mapped_column(String(20), default="zh_cn")
    company_type: Mapped[str] = mapped_column(String(40), default="unspecified")
    target_title: Mapped[str] = mapped_column(String(120), default="Agent 应用工程师")
    jd_text: Mapped[str] = mapped_column(Text, default="")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resume_project_id: Mapped[str] = mapped_column(ForeignKey("resume_projects.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("interview_targets.id"))
    status: Mapped[str] = mapped_column(String(30), default="in_progress")
    current_question_index: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=8)
    workflow_version: Mapped[str] = mapped_column(String(40), default="alpha-local-v1")
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(30))
    is_anchor: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt: Mapped[str] = mapped_column(Text)
    knowledge_point_id: Mapped[str] = mapped_column(String(120))
    rubric_version: Mapped[str] = mapped_column(String(60))
    signals_json: Mapped[str] = mapped_column(Text)


class AnswerAttempt(Base):
    __tablename__ = "answer_attempts"
    __table_args__ = (
        UniqueConstraint("session_id", "client_submission_id", name="uq_answer_submission"),
        UniqueConstraint("question_id", "primary_attempt_kind", name="uq_primary_answer"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("interview_questions.id"), index=True)
    client_submission_id: Mapped[str] = mapped_column(String(120))
    primary_attempt_kind: Mapped[str] = mapped_column(String(30), default="primary")
    status: Mapped[str] = mapped_column(String(30))
    answer_text: Mapped[str] = mapped_column(Text, default="")
    answer_text_hash: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AssessmentObservation(Base):
    __tablename__ = "assessment_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("answer_attempts.id"), unique=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("interview_questions.id"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    evidence_start: Mapped[int] = mapped_column(Integer)
    evidence_end: Mapped[int] = mapped_column(Integer)
    quoted_text: Mapped[str] = mapped_column(Text)
    answer_text_hash: Mapped[str] = mapped_column(String(64))
    gaps_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[float] = mapped_column()
    validity: Mapped[str] = mapped_column(String(30), default="valid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
