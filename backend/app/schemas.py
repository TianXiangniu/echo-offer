from typing import Literal

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


class ProjectAnalysisProject(BaseModel):
    project_name: str = Field(default="", max_length=200)
    background_goal: str = Field(default="", max_length=4000)
    tech_stack: str = Field(default="", max_length=4000)
    responsibilities: str = Field(default="", max_length=4000)
    core_solution: str = Field(default="", max_length=4000)
    engineering_challenges: str = Field(default="", max_length=4000)
    failure_improvements: str = Field(default="", max_length=4000)
    quantified_results: str = Field(default="", max_length=4000)


class ProjectAnalysisEvidence(BaseModel):
    field: ProjectFieldName
    quote: str = Field(min_length=1, max_length=2000)


class ProjectQuestionInput(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    knowledge_point_id: str = Field(min_length=1, max_length=120)
    signals: list[str] = Field(min_length=2, max_length=8)


class AgentProjectAnalysisResponse(BaseModel):
    project: ProjectAnalysisProject
    selection_reason: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    evidence: list[ProjectAnalysisEvidence] = Field(max_length=32)
    questions: list[ProjectQuestionInput] = Field(min_length=3, max_length=3)
    missing_information: list[str] = Field(max_length=32)


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


class AnswerResponse(BaseModel):
    answer: dict
    observation: ObservationResponse | None


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
