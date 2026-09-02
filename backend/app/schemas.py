from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectInput(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    background_goal: str = Field(min_length=1)
    tech_stack: str = Field(min_length=1)
    responsibilities: str = Field(min_length=1)
    core_solution: str = Field(min_length=1)
    engineering_challenges: str = Field(min_length=1)
    failure_improvements: str = Field(min_length=1)
    quantified_results: str = Field(default="", max_length=4000)


ProjectFieldName = Literal[
    "project_name",
    "background_goal",
    "tech_stack",
    "responsibilities",
    "core_solution",
    "engineering_challenges",
    "failure_improvements",
    "quantified_results",
]


class AgentProjectAnalysisRequest(BaseModel):
    resume_text: str = Field(min_length=1, max_length=100_000)


class ModelSettingsUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=160)
    assessment_model: str = Field(min_length=1, max_length=160)
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=256, le=8192)
    timeout_seconds: float = Field(ge=10, le=300)
    assessment_batch_size: int = Field(ge=1, le=5)


class ModelSettingsResponse(BaseModel):
    base_url: str
    model: str
    assessment_model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    assessment_batch_size: int
    api_key_configured: bool
    updated_at: datetime | None = None


class ModelConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    model: str
    latency_ms: int
    error_code: str | None = None


class ProjectAnalysisDetails(BaseModel):
    project_name: str = Field(default="", max_length=200)
    background_goal: str = Field(default="", max_length=4000)
    tech_stack: str = Field(default="", max_length=4000)
    responsibilities: str = Field(default="", max_length=4000)
    core_solution: str = Field(default="", max_length=4000)
    engineering_challenges: str = Field(default="", max_length=4000)
    failure_improvements: str = Field(default="", max_length=4000)
    quantified_results: str = Field(default="", max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)
    ownership: dict[str, Any] = Field(default_factory=dict)
    architecture: dict[str, Any] = Field(default_factory=dict)
    agent_details: dict[str, Any] = Field(default_factory=dict)
    tradeoffs: dict[str, Any] = Field(default_factory=dict)
    engineering: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    evolution: dict[str, Any] = Field(default_factory=dict)


ProjectAnalysisProject = ProjectAnalysisDetails


class ProjectAnalysisEvidence(BaseModel):
    field: ProjectFieldName
    quote: str = Field(min_length=1, max_length=2000)


ProjectFactStatus = Literal[
    "extracted",
    "confirmed",
    "inferred",
    "missing",
    "conflicting",
    "rejected",
]


class ProjectFactEvidence(BaseModel):
    quote: str = Field(min_length=1, max_length=2000)
    status: Literal["valid", "invalid"] = "valid"
    invalid_reason: str | None = Field(default=None, max_length=1000)
    start_offset: int | None = None
    end_offset: int | None = None
    text_hash: str | None = None


class ProjectFact(BaseModel):
    fact_id: str = Field(min_length=1, max_length=120)
    field: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=4000)
    status: ProjectFactStatus = "extracted"
    source_type: str = Field(default="", max_length=120)
    evidence: list[ProjectFactEvidence] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    user_confirmed: bool = False


class ProjectQuestionInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    knowledge_point_id: str = Field(min_length=1, max_length=120)
    signals: list[str] = Field(min_length=2, max_length=8)


ProjectQuestionGroup = Literal["project", "fixed"]


class ProjectQuestionDetail(BaseModel):
    order: int = Field(ge=1)
    question_group: ProjectQuestionGroup
    chain_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=1000)
    intent: str = Field(default="", max_length=1000)
    depends_on: int | None = None
    source_fields: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)
    expected_answer_points: list[str] = Field(default_factory=list)
    followup_if_incomplete: str = Field(default="", max_length=1000)
    followup_if_conflicting: str = Field(default="", max_length=1000)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class AgentProjectAnalysisResponse(BaseModel):
    project: ProjectAnalysisDetails
    selection_reason: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    evidence: list[ProjectAnalysisEvidence] = Field(max_length=32)
    questions: list[ProjectQuestionInput] = Field(min_length=3, max_length=3)
    missing_information: list[str] = Field(max_length=32)
    facts: list[ProjectFact] = Field(default_factory=list, max_length=32)
    question_chain: list[ProjectQuestionDetail] = Field(default_factory=list, max_length=32)


class AgentProjectAnalysisResponseEnvelope(AgentProjectAnalysisResponse):
    analysis_id: str
    resume_id: str
    resume_text_hash: str
    status: Literal["draft"]


class ProfileCreate(BaseModel):
    resume_text: str = Field(min_length=1, max_length=100_000)
    resume_id: str | None = None
    analysis_id: str | None = None
    project: ProjectInput
    project_questions: list[ProjectQuestionInput] | None = None


class ResumeParseResponse(BaseModel):
    resume_id: str
    source_type: Literal["pdf", "docx"]
    original_filename: str
    unit_count: int
    character_count: int
    extracted_text: str
    warnings: list[str]


class ProfileResponse(BaseModel):
    profile_id: str
    user_id: str
    project_version: int
    resume_text_hash: str
    direction: str
    level: str
    language: str


class SessionCreate(BaseModel):
    profile_id: str


class QuestionResponse(BaseModel):
    id: str
    order: int
    category: str
    is_anchor: bool
    prompt: str
    knowledge_point_id: str
    rubric_version: str


class SessionCreateResponse(BaseModel):
    session_id: str
    status: str
    questions: list[QuestionResponse]


class AnswerSubmission(BaseModel):
    question_id: str
    client_submission_id: str = Field(min_length=1, max_length=120)
    status: Literal["submitted", "explicit_unknown", "skipped"]
    answer_text: str = ""


class ObservationResponse(BaseModel):
    id: str
    level: int
    evidence_start: int
    evidence_end: int
    quoted_text: str
    confidence: float
    gaps: list[str]
    validity: str


class RubricObservationResponse(BaseModel):
    rubric_id: str
    level: int
    evidence_start: int
    evidence_end: int
    quoted_text: str
    confidence: float
    validity: str
    invalid_reason: str | None = None


class AssessmentResponse(BaseModel):
    status: str
    evaluator: str
    level: int | None = None
    confidence: float | None = None
    error_code: str | None = None
    error_reason: str | None = None
    rubric_items: list[RubricObservationResponse] = Field(default_factory=list)


class AssessmentBatchItemResponse(BaseModel):
    answer_id: str
    question_id: str
    assessment: AssessmentResponse


class AssessmentBatchResponse(BaseModel):
    status: str
    batch_id: str | None = None
    job_id: str | None = None
    job_status: str | None = None
    job_error_code: str | None = None
    job_error_message: str | None = None
    evaluated_count: int
    total_count: int
    assessments: list[AssessmentBatchItemResponse] = Field(default_factory=list)


class OperationJobEventResponse(BaseModel):
    sequence: int
    event_type: str
    progress: int
    message: str
    created_at: datetime


class OperationJobResponse(BaseModel):
    id: str
    operation_kind: str
    session_id: str | None = None
    assessment_batch_id: str | None = None
    status: str
    progress: int
    current_stage: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    events: list[OperationJobEventResponse] = Field(default_factory=list)


class AnswerResponse(BaseModel):
    answer: dict
    observation: ObservationResponse | None
    assessment: AssessmentResponse | None = None


class SessionView(BaseModel):
    session_id: str
    status: str
    current_question: QuestionResponse | None
    questions: list[dict]
    progress: dict[str, int]


class ReportResponse(BaseModel):
    session_id: str
    completion: dict[str, int]
    coverage: float
    anchor_coverage: dict[str, int]
    strengths: list[dict]
    gaps: list[dict]
    level_distribution: dict[str, int]
    valid_evidence_count: int
    confidence: float
    evaluator: str
    assessment_status_counts: dict[str, int] = Field(default_factory=dict)
    rubric_items: list[dict] = Field(default_factory=list)


class InterviewHistoryItem(BaseModel):
    session_id: str
    status: str
    direction: str | None = None
    target_title: str | None = None
    completed: int
    total: int
    report_status: str | None = None
    analysis_status: str | None = None
    created_at: datetime
    updated_at: datetime


class ProfileSkillResponse(BaseModel):
    skill_id: str
    skill_name: str
    category: str
    level: int
    confidence: float
    sample_count: int
    trend: str
    target_level: int | None = None
    last_session_id: str | None = None


class LearningRecommendationResponse(BaseModel):
    id: str
    skill_id: str
    skill_name: str
    priority: str
    reason: str
    actions: list[str]
    success_criteria: list[str]
    status: str
    recommended_review_at: datetime | None = None


class ProfileSummaryResponse(BaseModel):
    profile_id: str
    direction: str
    level: str
    target_title: str
    summary: str
    last_session_id: str | None = None
    skills: list[ProfileSkillResponse] = Field(default_factory=list)
    recommendations: list[LearningRecommendationResponse] = Field(default_factory=list)
    updated_at: datetime


class ProfileSnapshotResponse(BaseModel):
    id: str
    profile_id: str
    source_session_id: str
    version: int
    profile: dict
    created_at: datetime


class RecommendationStatusUpdate(BaseModel):
    status: Literal["recommended", "in_progress", "completed", "dismissed"]
