"""Deterministic shadow gates for the contextual interview graph."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_PLAN_KINDS = ("opening", "project", "architecture", "challenge", "tradeoff", "evidence")
ALLOWED_ROUTES = {"ask", "advance", "wrap_up"}


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("cases must be a list")
    return [case for case in cases if isinstance(case, dict)]


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    contract_rate = sum(
        tuple(case.get("plan_kinds", [])) == REQUIRED_PLAN_KINDS for case in cases
    ) / len(cases) if cases else 0.0
    routes = [route for case in cases for route in case.get("routes", [])]
    route_rate = sum(route in ALLOWED_ROUTES for route in routes) / len(routes) if routes else 0.0
    probes = [probe for case in cases for probe in case.get("probes", [])]
    contextual_rate = sum(bool(probe.get("references_previous_answer")) for probe in probes) / len(probes) if probes else 0.0
    grounded = [
        probe.get("fact_id") in set(case.get("verified_fact_ids", []))
        for case in cases
        for probe in case.get("probes", [])
    ]
    grounding_rate = sum(grounded) / len(grounded) if grounded else 0.0
    questions = [question for case in cases for question in case.get("normalized_questions", [])]
    duplicate_rate = 1 - (len(set(questions)) / len(questions)) if questions else 1.0
    model_calls = [int(case.get("model_calls", 0)) for case in cases]
    total_calls = sum(model_calls)
    total_cost = sum(float(case.get("estimated_cost_cny", 0)) for case in cases)
    gates = {
        "six_node_contract_pass_rate": round(contract_rate, 4),
        "route_validity_rate": round(route_rate, 4),
        "contextual_link_rate": round(contextual_rate, 4),
        "project_fact_grounding_rate": round(grounding_rate, 4),
        "duplicate_question_rate": round(duplicate_rate, 4),
        "six_node_contract_pass": contract_rate == 1.0,
        "route_validity_pass": route_rate == 1.0,
        "contextual_link_pass": contextual_rate >= 0.8,
        "project_fact_grounding_pass": grounding_rate >= 0.9,
        "duplicate_question_pass": duplicate_rate < 0.05,
        "all_pass": (
            contract_rate == 1.0
            and route_rate == 1.0
            and contextual_rate >= 0.8
            and grounding_rate >= 0.9
            and duplicate_rate < 0.05
        ),
    }
    return {
        "case_count": len(cases),
        "gates": gates,
        "mean_model_calls": round(total_calls / len(cases), 2) if cases else 0.0,
        "mean_model_call_cost_cny": round(total_cost / total_calls, 4) if total_calls else 0.0,
        "estimated_total_cost_cny": round(total_cost, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/evals/interview_graph_summary.json"))
    args = parser.parse_args()
    summary = evaluate_cases(load_cases(args.cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["gates"]["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
