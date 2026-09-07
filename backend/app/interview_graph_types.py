"""Serializable contracts for the contextual interview graph."""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


REQUIRED_PLAN_KINDS = {
    "opening",
    "project",
    "architecture",
    "challenge",
    "tradeoff",
    "evidence",
}
MAX_FOLLOWUPS_PER_NODE = 2


class InterviewGraphState(TypedDict):
    """JSON-serializable state persisted by LangGraph checkpoints."""

    session_id: str
    project: dict
    verified_facts: list[dict]
    plan: list[dict]
    current_node_index: int
    current_question: dict | None
    messages: Annotated[list[dict], operator.add]
    last_answer: dict | None
    coverage: dict[str, list[str]]
    conflicts: list[dict]
    followups_used: dict[str, int]
    route: Literal["conflict", "insufficient", "covered", "completed"]
    status: str
    error: dict | None


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
