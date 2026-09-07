from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from decimal import Decimal


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


class ModelPricePayload(BaseModel):
    model_name: str = Field(min_length=1, max_length=160)
    input_price_per_million_cny: Decimal = Field(ge=0)
    output_price_per_million_cny: Decimal = Field(ge=0)


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
    followup_enabled: bool = True
    practice_feedback_enabled: bool = True
    persona: Literal["gentle", "standard", "pressure"] = "standard"
    pricing: list[ModelPricePayload] = Field(default_factory=list)


class ModelSettingsResponse(BaseModel):
    base_url: str
    model: str
    assessment_model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    assessment_batch_size: int
    followup_enabled: bool
    practice_feedback_enabled: bool
    persona: str
    pricing: list[ModelPricePayload] = Field(default_factory=list)
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
    # ponytail: 允许纯手动项目（无简历文字）创建面试
    resume_text: str = Field(default="", max_length=100_000)
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
    mode: Literal["classic", "dialog", "graph"] = "classic"


class DialogAnswerSubmission(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class QuestionResponse(BaseModel):
    id: str
    order: int
    category: str
    is_anchor: bool
    prompt: str
    knowledge_point_id: str
    template_id: str | None = None
    rubric_version: str


class SessionCreateResponse(BaseModel):
    session_id: str
    status: str
    questions: list[QuestionResponse]


class GraphAnswerSubmission(BaseModel):
    answer_text: str = Field(min_length=1, max_length=8_000)
    client_submission_id: str = Field(min_length=1, max_length=120)


class AnswerSubmission(BaseModel):
    question_id: str
    client_submission_id: str = Field(min_length=1, max_length=120)
    status: Literal["submitted", "explicit_unknown", "skipped"]
    answer_text: str = ""


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
    assessment: AssessmentResponse | None = None


class FollowupView(BaseModel):
    id: str
    question_id: str
    question_text: str
    decision_reason: str
    status: str
    answer_text: str | None = None


class FollowupDecisionResponse(BaseModel):
    followup: FollowupView | None = None


class FollowupAnswerSubmission(BaseModel):
    client_submission_id: str = Field(min_length=1, max_length=120)
    answer_text: str = Field(min_length=1, max_length=8000)


class FollowupAnswerResponse(BaseModel):
    followup: FollowupView


class PracticeFeedbackView(BaseModel):
    question_id: str
    content: str
    focus_hints: list[str] = Field(default_factory=list)


class PracticeFeedbackResponse(BaseModel):
    feedback: PracticeFeedbackView | None = None


class PracticeSessionResponse(BaseModel):
    session_id: str
    session_kind: str


class OpenDrillRequest(BaseModel):
    skill_id: str | None = None


class SessionView(BaseModel):
    session_id: str
    status: str
    mode: str = "classic"
    stage: str = "knowledge"
    # dict 而非 QuestionResponse：追问/反馈状态要随当前题下发
    current_question: dict | None
    questions: list[dict]
    progress: dict[str, int]
    timeline: list[dict] = Field(default_factory=list)


class ReportResponse(BaseModel):
    session_id: str
    completion: dict[str, int]
    score_100: int | None = None
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
    transcript: list[dict] = Field(default_factory=list)


class InterviewHistoryItem(BaseModel):
    session_id: str
    status: str
    profile_id: str | None = None
    project_name: str | None = None
    direction: str | None = None
    target_title: str | None = None
    completed: int
    total: int
    score_100: int | None = None
    report_status: str | None = None
    analysis_status: str | None = None
    strength_count: int | None = None
    gap_count: int | None = None
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
    recent_levels: list[int] = Field(default_factory=list)
    studied: bool = False
    freshness: str = "no_data"
    days_since: int | None = None
    recent_answers: list[dict] = Field(default_factory=list)


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
    practice_completed_at: datetime | None = None
    verification_ready: bool = False
    source_session_id: str | None = None
    source_question_id: str | None = None
    source_question: str | None = None
    source_answer_excerpt: str | None = None
    source_level: int | None = Field(default=None, ge=0, le=4)
    level: int | None = Field(default=None, ge=0, le=4)
    studied: bool = False
    is_unknown: bool = False
    last_assessed_at: str | None = None


class ProfileSummaryResponse(BaseModel):
    profile_id: str
    direction: str
    level: str
    target_title: str
    summary: str
    last_session_id: str | None = None
    skills: list[ProfileSkillResponse] = Field(default_factory=list)
    recommendations: list[LearningRecommendationResponse] = Field(default_factory=list)
    recent_changes: list[dict] = Field(default_factory=list)
    readiness: int | None = None
    avg_target: float | None = None
    question_angles: list[dict] = Field(default_factory=list)
    practice_effectiveness: dict = Field(default_factory=dict)
    verifiable_count: int = 0
    target_date: datetime | None = None
    today_plan: list[dict] = Field(default_factory=list)
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


class SkillListResponse(BaseModel):
    skills: list[dict] = Field(default_factory=list)


class SkillDetailResponse(BaseModel):
    skill_id: str
    name: str
    category: str
    sections: dict
    has_deep_dive: bool
    mastery: dict
    studied: bool
    related_questions: list[dict] = Field(default_factory=list)
    community_questions: list[dict] = Field(default_factory=list)
    recent_answer: dict | None = None


class SkillStudyResponse(BaseModel):
    skill_id: str
    studied: bool


class TargetDateUpdate(BaseModel):
    date: str | None = Field(default=None, description="YYYY-MM-DD 或 null 清除")


class CommunityQuestionListResponse(BaseModel):
    total: int = 0
    questions: list[dict] = Field(default_factory=list)
    phases: list[dict] = Field(default_factory=list)
    knowledge_points: list[dict] = Field(default_factory=list)


class CommunityQuestionCreate(BaseModel):
    text: str = Field(min_length=4, max_length=4000)
    phase: str = Field(pattern="^(项目|八股|手撕|HR)$")
    knowledge_point: str = Field(default="未分类", max_length=120)
