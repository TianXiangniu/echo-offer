from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """SQLite 读回的 DateTime 无时区；统一按 UTC 处理。"""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelSetting(Base):
    __tablename__ = "model_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_model_settings_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    base_url: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(160))
    assessment_model: Mapped[str] = mapped_column(String(160))
    temperature: Mapped[float] = mapped_column()
    max_tokens: Mapped[int] = mapped_column(Integer)
    timeout_seconds: Mapped[float] = mapped_column()
    assessment_batch_size: Mapped[int] = mapped_column(Integer)
    followup_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    practice_feedback_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    persona: Mapped[str] = mapped_column(String(20), default="standard")
    pricing_json: Mapped[str] = mapped_column(Text, default="[]")
    api_key: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


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
    analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    project_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResumeProjectAnalysis(Base):
    __tablename__ = "resume_project_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resume_text_hash: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(120))
    provider_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ResumeProjectQuestion(Base):
    __tablename__ = "resume_project_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_project_id: Mapped[str] = mapped_column(ForeignKey("resume_projects.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)
    knowledge_point_id: Mapped[str] = mapped_column(String(120))
    signals_json: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))
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
    # 目标面试日期：画像倒排训练计划用
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resume_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_projects.id"), nullable=True
    )
    target_id: Mapped[str] = mapped_column(ForeignKey("interview_targets.id"))
    status: Mapped[str] = mapped_column(String(30), default="in_progress")
    current_question_index: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=8)
    followup_budget_used: Mapped[int] = mapped_column(Integer, default=0)
    session_kind: Mapped[str] = mapped_column(String(20), default="interview")
    # SQLite 无法 ALTER 添加外键，关联语义由应用层维护（指向 learning_recommendations.id）
    source_recommendation_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    # 对话式面试：mode=dialog 走 intro→深挖→knowledge→wrap_up 流程；classic 为既有流程
    mode: Mapped[str] = mapped_column(String(20), default="classic")
    stage: Mapped[str] = mapped_column(String(20), default="knowledge")
    dialog_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workflow_version: Mapped[str] = mapped_column(String(40), default="alpha-local-v1")
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_profiles.id"), index=True, nullable=True
    )
    current_assessment_run_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    current_assessment_batch_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    current_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    template_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    rubric_version: Mapped[str] = mapped_column(String(60))
    signals_json: Mapped[str] = mapped_column(Text)
    rubric_json: Mapped[str] = mapped_column(Text, default="{}")


class InterviewFollowup(Base):
    __tablename__ = "interview_followups"
    __table_args__ = (
        UniqueConstraint("question_id", "round", name="uq_followup_question_round"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("interview_questions.id"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    question_text: Mapped[str] = mapped_column(Text, default="")
    decision_reason: Mapped[str] = mapped_column(String(30), default="probe")
    client_submission_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionFeedback(Base):
    """逐题练习反馈。与盲评分严格隔离：评分链路不读取本表。"""

    __tablename__ = "question_feedbacks"
    __table_args__ = (
        UniqueConstraint("question_id", name="uq_question_feedback"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("interview_questions.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    focus_hints_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProjectDialog(Base):
    """对话式面试的消息流：面试官的话与候选人的回答逐条落库。"""

    __tablename__ = "project_dialogs"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_no", "role", name="uq_dialog_turn_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id"), index=True
    )
    turn_no: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))  # interviewer | candidate
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="dialog")
    heuristic_tag: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InterviewGraphEventReceipt(Base):
    """Durable idempotency receipt for LangGraph-to-legacy projections."""

    __tablename__ = "interview_graph_event_receipts"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "graph_step_id",
            "event_kind",
            name="uq_graph_event_session_step_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    graph_step_id: Mapped[str] = mapped_column(String(160))
    event_kind: Mapped[str] = mapped_column(String(60))
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InterviewGraphSubmissionReceipt(Base):
    """Durable reservation preventing duplicate graph work across workers."""

    __tablename__ = "interview_graph_submission_receipts"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "client_submission_id",
            name="uq_graph_submission_session_client",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    client_submission_id: Mapped[str] = mapped_column(String(120))
    answer_text_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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


class AssessmentRun(Base):
    __tablename__ = "assessment_runs"
    __table_args__ = (
        UniqueConstraint("answer_id", "attempt_number", name="uq_assessment_attempt"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("answer_attempts.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("interview_questions.id"), index=True)
    plan_node_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    evaluator: Mapped[str] = mapped_column(String(80))
    rubric_version: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    aggregate_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aggregate_confidence: Mapped[float | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    commentary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    assessment_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessment_batches.id"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AssessmentBatch(Base):
    __tablename__ = "assessment_batches"
    __table_args__ = (
        UniqueConstraint("session_id", "attempt_number", name="uq_assessment_batch_attempt"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    operation_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    evaluator: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RubricObservation(Base):
    __tablename__ = "rubric_observations"
    __table_args__ = (
        UniqueConstraint("assessment_run_id", "rubric_id", name="uq_rubric_run_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assessment_run_id: Mapped[str] = mapped_column(ForeignKey("assessment_runs.id"), index=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("answer_attempts.id"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("interview_questions.id"), index=True)
    rubric_id: Mapped[str] = mapped_column(String(80))
    rubric_version: Mapped[str] = mapped_column(String(60))
    level: Mapped[int] = mapped_column(Integer)
    evidence_start: Mapped[int] = mapped_column(Integer)
    evidence_end: Mapped[int] = mapped_column(Integer)
    quoted_text: Mapped[str] = mapped_column(Text)
    answer_text_hash: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column()
    validity: Mapped[str] = mapped_column(String(30), default="valid")
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OperationJob(Base):
    __tablename__ = "operation_jobs"
    __table_args__ = (
        UniqueConstraint("operation_kind", "idempotency_key", name="uq_operation_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interview_sessions.id"), index=True, nullable=True
    )
    assessment_batch_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    operation_kind: Mapped[str] = mapped_column(String(60), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[str] = mapped_column(String(80), default="queued")
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    raw_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OperationJobEvent(Base):
    __tablename__ = "operation_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_operation_event_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("operation_jobs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(30))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LlmCallTrace(Base):
    __tablename__ = "llm_call_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interview_sessions.id"), index=True, nullable=True
    )
    operation_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation_jobs.id"), index=True, nullable=True
    )
    call_kind: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    model_name: Mapped[str] = mapped_column(String(160), index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_price_per_million_cny: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    output_price_per_million_cny: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cost_cny: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    request_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class EvidenceSpan(Base):
    __tablename__ = "evidence_spans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey("rubric_observations.id"), index=True)
    answer_id: Mapped[str] = mapped_column(ForeignKey("answer_attempts.id"), index=True)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    quoted_text: Mapped[str] = mapped_column(Text)
    answer_text_hash: Mapped[str] = mapped_column(String(64))
    validity: Mapped[str] = mapped_column(String(30), default="valid")
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InterviewReport(Base):
    __tablename__ = "interview_reports"
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_report_session_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    assessment_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assessment_batch_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SkillCatalog(Base):
    __tablename__ = "skill_catalog"
    __table_args__ = (
        UniqueConstraint("canonical_name", name="uq_skill_canonical_name"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), default="general")
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SkillWiki(Base):
    """知识点讲解页。content_json 结构化存储各区块，深讲按需生成后覆盖写回。"""

    __tablename__ = "skill_wikis"

    skill_id: Mapped[str] = mapped_column(
        ForeignKey("skill_catalog.id"), primary_key=True
    )
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    has_deep_dive: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="preset")
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SkillStudyLog(Base):
    """学习流水：只记"学过"，掌握度仍由评分驱动（学过≠会了）。"""

    __tablename__ = "skill_study_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_catalog.id"), index=True)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    studied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QuestionSkill(Base):
    __tablename__ = "question_skills"
    __table_args__ = (
        UniqueConstraint("question_id", "skill_id", name="uq_question_skill"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("interview_questions.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_catalog.id"), index=True)
    weight: Mapped[float] = mapped_column(default=1.0)


class RoleSkillRequirement(Base):
    __tablename__ = "role_skill_requirements"
    __table_args__ = (
        UniqueConstraint("direction", "level", "skill_id", name="uq_role_skill_requirement"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    direction: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[str] = mapped_column(String(80), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_catalog.id"), index=True)
    target_level: Mapped[int] = mapped_column(Integer)
    importance_weight: Mapped[float] = mapped_column(default=1.0)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "direction", "level", "target_title",
            name="uq_candidate_profile_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    direction: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[str] = mapped_column(String(80), index=True)
    target_title: Mapped[str] = mapped_column(String(120))
    current_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CandidateKnowledgeState(Base):
    __tablename__ = "candidate_knowledge_states"
    __table_args__ = (
        UniqueConstraint("profile_id", "skill_id", name="uq_candidate_profile_skill_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_catalog.id"), index=True)
    current_level: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(default=0.0)
    valid_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    trend: Mapped[str] = mapped_column(String(20), default="insufficient_data")
    serious_error_count: Mapped[int] = mapped_column(Integer, default=0)
    first_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_profile_snapshot_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    source_session_id: Mapped[str] = mapped_column(ForeignKey("interview_sessions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LearningRecommendation(Base):
    __tablename__ = "learning_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"), index=True)
    profile_snapshot_id: Mapped[str] = mapped_column(ForeignKey("profile_snapshots.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_catalog.id"), index=True)
    priority: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(Text)
    actions_json: Mapped[str] = mapped_column(Text, default="[]")
    success_criteria_json: Mapped[str] = mapped_column(Text, default="[]")
    recommended_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    practice_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="recommended", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CommunityQuestion(Base):
    """社区题库：从面经帖抽取的真实面试题。

    knowledge_point_slug 暂存字符串、不建外键，待与知识库知识点体系联动时再升级。
    """

    __tablename__ = "community_questions"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_community_question_content"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    phase: Mapped[str] = mapped_column(String(20), index=True)
    knowledge_point_slug: Mapped[str] = mapped_column(String(120), index=True)
    note_url: Mapped[str] = mapped_column(Text, default="")
    note_id: Mapped[str] = mapped_column(String(80), index=True)
    dup_count: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
