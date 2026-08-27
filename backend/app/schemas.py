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
    quantified_results: str = Field(min_length=1)


class ProfileCreate(BaseModel):
    resume_text: str = Field(min_length=1)
    resume_id: str | None = None
    project: ProjectInput


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
