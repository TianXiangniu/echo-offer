"""Serializable contracts for the contextual interview graph."""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator


REQUIRED_PLAN_KINDS = {
    "opening",
    "project",
    "architecture",
    "challenge",
    "tradeoff",
    "evidence",
}
MAX_FOLLOWUPS_PER_NODE = 2


class ProjectSummaryState(TypedDict):
    project_id: str
    name: str
    summary: str


class VerifiedFactState(TypedDict):
    fact_id: str
    summary: str
    source: Literal["resume", "candidate"]


class InterviewPlanNodeState(TypedDict):
    node_id: str
    kind: str
    goal: str
    project_fact_ids: list[str]
    required_targets: list[str]
    opening_question: str
    rubric_ids: list[str]
    max_followups: int


class QuestionState(TypedDict):
    node_id: str
    text: str
    kind: Literal["opening", "followup", "clarification", "wrap_up"]


class MessageState(TypedDict):
    role: Literal["interviewer", "candidate"]
    node_id: str
    content: str


class GraphEventState(TypedDict):
    session_id: str
    graph_step_id: str
    event_kind: Literal["question_ready", "candidate_answer", "completed"]
    payload: dict


class CandidateAnswerState(TypedDict):
    node_id: str
    content: str


class ConflictState(TypedDict):
    target: str
    detail: str


class GraphErrorState(TypedDict):
    code: str
    message: str


class InterviewGraphState(TypedDict):
    """Safe, JSON-only state persisted by LangGraph checkpoints."""

    session_id: str
    project: ProjectSummaryState
    verified_facts: list[VerifiedFactState]
    plan: list[InterviewPlanNodeState]
    current_node_index: int
    current_question: QuestionState | None
    messages: Annotated[list[MessageState], operator.add]
    graph_events: Annotated[list[GraphEventState], operator.add]
    last_answer: CandidateAnswerState | None
    coverage: dict[str, list[str]]
    conflicts: list[ConflictState]
    followups_used: dict[str, int]
    route: Literal["conflict", "insufficient", "covered", "completed"]
    status: Literal["planning", "awaiting_answer", "verifying", "completed", "failed"]
    error: GraphErrorState | None


class ProjectSummaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: StrictStr = Field(min_length=1, max_length=128)
    name: StrictStr = Field(min_length=1, max_length=200)
    summary: StrictStr = Field(min_length=1, max_length=2_000)


class VerifiedFactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: StrictStr = Field(min_length=1, max_length=128)
    summary: StrictStr = Field(min_length=1, max_length=1_000)
    source: Literal["resume", "candidate"]


class QuestionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: StrictStr = Field(min_length=1, max_length=128)
    text: StrictStr = Field(min_length=1, max_length=4_000)
    kind: Literal["opening", "followup", "clarification", "wrap_up"]


class MessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["interviewer", "candidate"]
    node_id: StrictStr = Field(min_length=1, max_length=128)
    content: StrictStr = Field(min_length=1, max_length=8_000)


class CandidateAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: StrictStr = Field(min_length=1, max_length=128)
    content: StrictStr = Field(min_length=1, max_length=8_000)


class ConflictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: StrictStr = Field(min_length=1, max_length=256)
    detail: StrictStr = Field(min_length=1, max_length=1_000)


class GraphErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: StrictStr = Field(min_length=1, max_length=128)
    message: StrictStr = Field(min_length=1, max_length=1_000)


class InterviewGraphStatePayload(BaseModel):
    """Runtime validator that converts safe payloads to checkpoint dictionaries."""

    model_config = ConfigDict(extra="forbid")

    session_id: StrictStr = Field(min_length=1, max_length=128)
    project: ProjectSummaryPayload
    verified_facts: list[VerifiedFactPayload]
    plan: list["InterviewPlanNode"]
    current_node_index: int = Field(ge=0)
    current_question: QuestionPayload | None
    messages: list[MessagePayload]
    last_answer: CandidateAnswerPayload | None
    coverage: dict[StrictStr, list[StrictStr]]
    conflicts: list[ConflictPayload]
    followups_used: dict[
        StrictStr, Annotated[int, Field(ge=0, le=MAX_FOLLOWUPS_PER_NODE)]
    ]
    route: Literal["conflict", "insufficient", "covered", "completed"]
    status: Literal["planning", "awaiting_answer", "verifying", "completed", "failed"]
    error: GraphErrorPayload | None

    @model_validator(mode="after")
    def validate_plan(self) -> "InterviewGraphStatePayload":
        InterviewPlan(nodes=self.plan)
        return self


class InterviewPlanNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: str
    goal: str
    project_fact_ids: list[str]
    required_targets: list[str]
    opening_question: str
    rubric_ids: list[str]
    max_followups: int = Field(ge=0, le=MAX_FOLLOWUPS_PER_NODE)


class InterviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[InterviewPlanNode]

    @model_validator(mode="after")
    def validate_nodes(self) -> "InterviewPlan":
        if len(self.nodes) != len(REQUIRED_PLAN_KINDS):
            raise ValueError("an interview plan must contain exactly six nodes")
        if len({node.node_id for node in self.nodes}) != len(self.nodes):
            raise ValueError("interview plan node_id values must be unique")
        if {node.kind for node in self.nodes} != REQUIRED_PLAN_KINDS:
            raise ValueError("interview plan must contain every required kind once")
        return self


class InterviewerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    rationale: str
    followups_used: int = Field(ge=0, le=MAX_FOLLOWUPS_PER_NODE)


class EvidenceVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[str]
    covered_targets: list[str]
    missing_targets: list[str]
    conflicts: list[str]
    confidence: float = Field(ge=0, le=1)
    route: Literal["conflict", "insufficient", "covered"]
