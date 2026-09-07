"""Role-separated model calls for the contextual interview graph."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .interview_graph_types import EvidenceVerification, InterviewPlan, MAX_FOLLOWUPS_PER_NODE
from .llm_observability import (
    INTERVIEW_AGENT_CALL_KINDS,
)
from .model_output import parse_model_json
from .model_settings import ModelSettingsValues
from .prompts import (
    EVIDENCE_VERIFIER_PROMPT_VERSION,
    GRAPH_INTERVIEWER_PROMPT_VERSION,
    PLANNER_PROMPT_VERSION,
    build_evidence_verifier_prompt,
    build_graph_interviewer_prompt,
    build_planner_prompt,
)
from .providers import _SiliconFlowClient


class PlannerAgent(Protocol):
    def plan(self, context: Mapping) -> InterviewPlan: ...


class InterviewerAgent(Protocol):
    def ask(self, context: Mapping) -> "InterviewerTurnOutput": ...


class EvidenceVerifierAgent(Protocol):
    def verify(self, context: Mapping) -> EvidenceVerification: ...


class InterviewerTurnOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=150)
    kind: str = Field(default="followup", pattern="^(opening|followup|clarification|wrap_up)$")
    rationale: str = Field(default="", max_length=300)
    referenced_quote: str = Field(default="", max_length=200)
    followups_used: int = Field(default=0, ge=0, le=MAX_FOLLOWUPS_PER_NODE)


def _object(content: object) -> dict:
    payload = parse_model_json(content)
    if not isinstance(payload, dict):
        raise ValueError("model output must be a JSON object")
    return payload


def _compact(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def parse_interview_plan(content: object) -> InterviewPlan:
    payload = _object(content)
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ValueError("planner output must contain nodes")
    nodes = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            nodes.append(raw)
            continue
        node = dict(raw)
        for key, limit in (("node_id", 128), ("kind", 64), ("goal", 500), ("opening_question", 150)):
            if key in node:
                node[key] = _compact(node[key], limit)
        nodes.append(node)
    return InterviewPlan.model_validate({"nodes": nodes})


def parse_interviewer_turn(content: object) -> InterviewerTurnOutput:
    payload = _object(content)
    question = _compact(payload.get("question"), 150)
    if not question:
        raise ValueError("interviewer output missing question")
    kind = payload.get("kind", "followup")
    if kind not in {"opening", "followup", "clarification", "wrap_up"}:
        kind = "followup"
    referenced_quote = _compact(payload.get("referenced_quote"), 200)
    if kind in {"followup", "clarification"} and not referenced_quote:
        raise ValueError("last answer reference is required for follow-up")
    return InterviewerTurnOutput(
        question=question,
        kind=kind,
        rationale=_compact(payload.get("rationale"), 300),
        referenced_quote=referenced_quote,
        followups_used=payload.get("followups_used", 0),
    )


def parse_evidence_verification(content: object) -> EvidenceVerification:
    payload = _object(content)
    for key in ("claims", "covered_targets", "missing_targets", "conflicts"):
        if isinstance(payload.get(key), list):
            payload[key] = [_compact(item, 500) for item in payload[key] if str(item).strip()][:20]
    return EvidenceVerification.model_validate(payload)


def _current_node(context: Mapping) -> dict:
    if isinstance(context.get("current_node"), Mapping):
        return dict(context["current_node"])
    plan = context.get("plan", [])
    index = context.get("current_node_index", 0)
    if isinstance(plan, list) and isinstance(index, int) and 0 <= index < len(plan):
        return dict(plan[index]) if isinstance(plan[index], Mapping) else {}
    return {}


def _interviewer_context(context: Mapping) -> dict:
    verifier = context.get("verifier_result")
    if not isinstance(verifier, Mapping):
        verifier = {
            "route": context.get("route", ""),
            "missing_targets": context.get("missing_targets", []),
        }
    return {
        "current_node": _current_node(context),
        "last_answer": context.get("last_answer"),
        "verifier_result": dict(verifier),
        "messages": context.get("messages", []),
    }


def _verifier_context(context: Mapping) -> dict:
    node = _current_node(context)
    return {
        "current_question": context.get("current_question", {}),
        "answer": context.get("answer") or context.get("last_answer", {}),
        "allowed_facts": context.get("allowed_facts") or context.get("verified_facts", []),
        "required_targets": context.get("required_targets") or node.get("required_targets", []),
    }


class SiliconFlowInterviewAgents(PlannerAgent, InterviewerAgent, EvidenceVerifierAgent):
    """Three role-specific calls sharing the existing SiliconFlow client."""

    def __init__(self, settings: ModelSettingsValues, *, client=None):
        self._client = _SiliconFlowClient(
            settings.api_key,
            settings.model,
            settings.base_url,
            settings.timeout_seconds,
            settings.temperature,
            min(settings.max_tokens, 2400),
            client,
        )

    def _call(self, system: str, user: str, parser, *, kind: str, version: str):
        if kind not in INTERVIEW_AGENT_CALL_KINDS:
            raise ValueError(f"unknown interview agent call kind: {kind}")
        return self._client.chat_json(
            system,
            user,
            parser,
            call_kind=kind,
            prompt_version=version,
        )

    def plan(self, context: Mapping) -> InterviewPlan:
        return self._call(*build_planner_prompt(dict(context)), parse_interview_plan,
                          kind="planner", version=PLANNER_PROMPT_VERSION)

    def ask(self, context: Mapping) -> InterviewerTurnOutput:
        return self._call(*build_graph_interviewer_prompt(_interviewer_context(context)), parse_interviewer_turn,
                          kind="interviewer", version=GRAPH_INTERVIEWER_PROMPT_VERSION)

    def verify(self, context: Mapping) -> EvidenceVerification:
        return self._call(*build_evidence_verifier_prompt(_verifier_context(context)), parse_evidence_verification,
                          kind="evidence_verifier", version=EVIDENCE_VERIFIER_PROMPT_VERSION)
