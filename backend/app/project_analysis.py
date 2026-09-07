import json

from pydantic import ValidationError

from .model_output import ModelOutputError, parse_model_json
from .prompts import ANALYSIS_PROMPT_VERSION, ANALYSIS_SYSTEM_PROMPT
from .schemas import AgentProjectAnalysisResponse, ProjectQuestionDetail

# 兼容既有导入路径；提示词正文本体在 prompts.py
SYSTEM_PROMPT = ANALYSIS_SYSTEM_PROMPT


def build_user_prompt(resume_text: str) -> str:
    return f"""从下面完整简历中，选择与 Agent/RAG/LLM 最相关且信息最完整的一个项目。

## 输出要求
只输出一个 JSON object，不要 Markdown、不要解释。顶层结构如下（省略号处填内容）：

{{
  "project": {{
    "project_name": "...", "background_goal": "...", "tech_stack": "...",
    "responsibilities": "...", "core_solution": "...", "engineering_challenges": "...",
    "failure_improvements": "...", "quantified_results": "...",
    "context": {{}}, "ownership": {{}}, "architecture": {{}}, "agent_details": {{}},
    "tradeoffs": {{}}, "engineering": {{}}, "evaluation": {{}}, "evolution": {{}}
  }},
  "selection_reason": "...",
  "confidence": 0.0,
  "evidence": [{{"field": "project_name", "quote": "逐字来自简历"}}],
  "facts": [{{"fact_id": "f1", "field": "...", "value": "...", "status": "extracted",
              "source_type": "resume_direct", "evidence": [{{"quote": "逐字来自简历"}}],
              "confidence": 0.9, "user_confirmed": false}}],
  "questions": [{{"prompt": "...", "knowledge_point_id": "project.ownership_and_context", "signals": ["...", "..."]}},
                {{...第二问...}}, {{...第三问...}}],
  "question_chain": [{{"order": 1, "question_group": "project", "chain_id": "c1", "prompt": "...",
                       "intent": "...", "depends_on": null, "source_fields": [], "source_fact_ids": [],
                       "expected_answer_points": ["...", "..."], "followup_if_incomplete": "...",
                       "followup_if_conflicting": "...", "difficulty": "easy|medium|hard"}},
                      {{...order 2, depends_on: 1...}}, {{...order 3, depends_on: 2...}}],
  "missing_information": ["..."]
}}

## 填写规则
1. project 八个核心字段必须保留；context/ownership/architecture/agent_details/tradeoffs/engineering/evaluation/evolution 八个分组只在简历有明确信息时填写，否则返回空对象——缺失信息统一写进 missing_information，不要猜测。
2. ownership 要区分你亲自负责的部分与团队/共享部分；context 要写规模、流量、数据量、并发、延迟或影响范围；tradeoffs 要写选型取舍、备选方案和放弃原因；evaluation 要写验证方法、指标、基线或线上验证方式。
3. evidence 的 quote 必须逐字来自简历。
4. facts 的 status 只能是 extracted、confirmed、inferred、missing、conflicting、rejected 之一；
   source_type 只能是 resume_direct（简历原文直述）、resume_inferred（由原文推断）、question_lead（仅可作开放确认提问的线索）之一。
   只有 status 为 extracted 或 confirmed 的 fact 才能作为问题前提；inferred/missing/conflicting 只能作为开放确认提问的线索。
5. questions 必须恰好三道并形成依赖链：第 1 问确认职责和背景（knowledge_point_id 用 project.ownership_and_context）；第 2 问追问方案、边界或取舍（project.architecture_tradeoffs）；第 3 问追问评估方法、结果或复现（project.evaluation_and_reproducibility）。每问的 signals 给 2-4 个关键词。
6. question_chain 同样三条、顺序链接。每问必须给出 expected_answer_points（2-4 条这个问题的合格回答应覆盖的要点）、
   followup_if_incomplete（若回答不完整，追问什么）和 followup_if_conflicting（若回答与简历矛盾或含糊，追问什么）、
   difficulty（easy/medium/hard 之一）。这三类字段会在后续追问环节直接使用，务必具体。
7. 只填写与简历明确相关的类别，控制 token 输出，不要扩写长段落。

简历：
<resume>
{resume_text}
</resume>
"""


_PROJECT_TEXT_FIELDS = (
    "project_name",
    "background_goal",
    "tech_stack",
    "responsibilities",
    "core_solution",
    "engineering_challenges",
    "failure_improvements",
    "quantified_results",
)

_QUESTION_METADATA = (
    ("project.ownership_and_context", ["职责", "背景"]),
    ("project.architecture_tradeoffs", ["方案", "取舍"]),
    ("project.evaluation_and_reproducibility", ["难点", "效果"]),
)

_PROJECT_NESTED_GROUP_FIELDS = (
    "context",
    "ownership",
    "architecture",
    "agent_details",
    "tradeoffs",
    "engineering",
    "evaluation",
    "evolution",
)


def _model_value_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        values = [_model_value_to_text(item) for item in value]
        return "；".join(item for item in values if item)
    if isinstance(value, dict):
        values = (
            f"{key}：{_model_value_to_text(item)}"
            for key, item in value.items()
        )
        return "；".join(item for item in values if not item.endswith("："))
    return str(value)


def normalize_model_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")

    normalized = dict(payload)
    project = dict(payload.get("project") or {})
    for field in _PROJECT_TEXT_FIELDS:
        project[field] = _model_value_to_text(project.get(field, ""))
    normalized["project"] = project

    normalized.setdefault(
        "selection_reason",
        "根据简历中与 Agent/RAG/LLM 相关的项目内容进行选择。",
    )
    try:
        normalized["confidence"] = float(normalized.get("confidence", 0))
    except (TypeError, ValueError):
        normalized["confidence"] = 0.0

    evidence = normalized.get("evidence", [])
    if isinstance(evidence, dict):
        evidence = [evidence]
    if isinstance(evidence, list):
        normalized_evidence = []
        for item in evidence:
            if isinstance(item, dict):
                item = dict(item)
                quote = _model_value_to_text(item.get("quote"))
                item["quote"] = quote
                field = _model_value_to_text(item.get("field"))
                if not field:
                    field = next(
                        (
                            project_field
                            for project_field in _PROJECT_TEXT_FIELDS
                            if quote and quote in project.get(project_field, "")
                        ),
                        "project_name",
                    )
                item["field"] = field
            normalized_evidence.append(item)
        evidence = normalized_evidence
    normalized["evidence"] = evidence

    questions = normalized.get("questions", [])
    if isinstance(questions, list) and len(questions) == 3:
        normalized_questions = []
        for question, (knowledge_point_id, signals) in zip(questions, _QUESTION_METADATA):
            if isinstance(question, str):
                question = {"prompt": question}
            elif not isinstance(question, dict):
                question = {"prompt": _model_value_to_text(question)}
            else:
                question = dict(question)
            question["prompt"] = _model_value_to_text(question.get("prompt", ""))
            question["knowledge_point_id"] = (
                _model_value_to_text(question.get("knowledge_point_id"))
                or knowledge_point_id
            )
            question_signals = question.get("signals")
            if not isinstance(question_signals, list) or len(question_signals) < 2:
                question["signals"] = signals
            else:
                question["signals"] = [
                    _model_value_to_text(signal) for signal in question_signals
                ]
            normalized_questions.append(question)
        normalized["questions"] = normalized_questions

    missing_information = normalized.get("missing_information", [])
    if isinstance(missing_information, list):
        normalized["missing_information"] = [
            _model_value_to_text(item) for item in missing_information
        ]
    elif missing_information:
        normalized["missing_information"] = [_model_value_to_text(missing_information)]
    else:
        normalized["missing_information"] = []

    return normalized


def _normalize_fact_evidence(evidence: object, resume_text: str) -> list[dict]:
    if isinstance(evidence, dict):
        evidence = [evidence]
    if not isinstance(evidence, list):
        return []

    normalized_evidence: list[dict] = []
    for item in evidence:
        if isinstance(item, dict):
            normalized_item = dict(item)
        else:
            normalized_item = {"quote": _model_value_to_text(item)}
        quote = _model_value_to_text(normalized_item.get("quote"))
        normalized_item["quote"] = quote
        if not resume_text:
            normalized_item["status"] = _model_value_to_text(
                normalized_item.get("status")
            ) or "valid"
            normalized_item.pop("invalid_reason", None)
        elif quote and quote in resume_text:
            normalized_item["status"] = _model_value_to_text(
                normalized_item.get("status")
            ) or "valid"
            if normalized_item["status"] != "invalid":
                normalized_item.pop("invalid_reason", None)
        else:
            normalized_item["status"] = "invalid"
            normalized_item["invalid_reason"] = _model_value_to_text(
                normalized_item.get("invalid_reason")
            ) or "证据不在简历中"
        normalized_evidence.append(normalized_item)
    return normalized_evidence


def _normalize_fact_payload(fact: object, resume_text: str) -> dict:
    normalized_fact = dict(fact) if isinstance(fact, dict) else {}
    normalized_fact["fact_id"] = _model_value_to_text(
        normalized_fact.get("fact_id")
    )
    normalized_fact["field"] = _model_value_to_text(normalized_fact.get("field"))
    normalized_fact["value"] = _model_value_to_text(normalized_fact.get("value"))
    normalized_fact["status"] = _model_value_to_text(
        normalized_fact.get("status")
    ) or "extracted"
    normalized_fact["source_type"] = _model_value_to_text(
        normalized_fact.get("source_type")
    )
    normalized_fact["evidence"] = _normalize_fact_evidence(
        normalized_fact.get("evidence", []),
        resume_text,
    )
    try:
        normalized_fact["confidence"] = float(normalized_fact.get("confidence", 0))
    except (TypeError, ValueError):
        normalized_fact["confidence"] = 0.0
    normalized_fact["user_confirmed"] = bool(normalized_fact.get("user_confirmed", False))
    return normalized_fact


def _normalize_question_chain(question_chain: object) -> list[dict]:
    if not isinstance(question_chain, list) or len(question_chain) != 3:
        return []

    normalized_chain: list[dict] = []
    for expected_order, raw_item in enumerate(question_chain, start=1):
        if not isinstance(raw_item, dict):
            return []
        normalized_item = dict(raw_item)
        normalized_item["order"] = normalized_item.get("order", expected_order)
        normalized_item["question_group"] = _model_value_to_text(
            normalized_item.get("question_group")
        )
        normalized_item["chain_id"] = _model_value_to_text(
            normalized_item.get("chain_id")
        )
        normalized_item["prompt"] = _model_value_to_text(normalized_item.get("prompt"))
        normalized_item["intent"] = _model_value_to_text(normalized_item.get("intent"))
        normalized_item["depends_on"] = normalized_item.get("depends_on")
        source_fields = normalized_item.get("source_fields")
        if isinstance(source_fields, list):
            normalized_item["source_fields"] = [
                _model_value_to_text(item) for item in source_fields
            ]
        else:
            normalized_item["source_fields"] = []
        source_fact_ids = normalized_item.get("source_fact_ids")
        if isinstance(source_fact_ids, list):
            normalized_item["source_fact_ids"] = [
                _model_value_to_text(item) for item in source_fact_ids
            ]
        else:
            normalized_item["source_fact_ids"] = []
        expected_answer_points = normalized_item.get("expected_answer_points")
        if isinstance(expected_answer_points, list):
            normalized_item["expected_answer_points"] = [
                _model_value_to_text(item) for item in expected_answer_points
            ]
        else:
            normalized_item["expected_answer_points"] = []
        normalized_item["followup_if_incomplete"] = _model_value_to_text(
            normalized_item.get("followup_if_incomplete")
        )
        normalized_item["followup_if_conflicting"] = _model_value_to_text(
            normalized_item.get("followup_if_conflicting")
        )
        normalized_item["difficulty"] = _model_value_to_text(
            normalized_item.get("difficulty")
        ) or "medium"
        try:
            validated_item = ProjectQuestionDetail.model_validate(normalized_item)
        except ValidationError:
            return []
        normalized_chain.append(validated_item.model_dump())

    if [item["order"] for item in normalized_chain] != [1, 2, 3]:
        return []
    if [item["depends_on"] for item in normalized_chain] != [None, 1, 2]:
        return []
    if any(item["question_group"] != "project" for item in normalized_chain):
        return []
    return normalized_chain


def normalize_project_analysis_payload(payload: object, resume_text: str) -> dict:
    normalized = normalize_model_payload(payload)
    normalized["schema_version"] = _model_value_to_text(
        normalized.get("schema_version")
    ) or "project-analysis-v2"
    normalized.setdefault("prompt_version", ANALYSIS_PROMPT_VERSION)

    project = dict(normalized.get("project") or {})
    for field in _PROJECT_NESTED_GROUP_FIELDS:
        value = project.get(field)
        project[field] = dict(value) if isinstance(value, dict) else {}
    normalized["project"] = project

    facts = normalized.get("facts", [])
    if isinstance(facts, dict):
        facts = [facts]
    if isinstance(facts, list):
        normalized["facts"] = [
            _normalize_fact_payload(fact, resume_text) for fact in facts if fact is not None
        ]
    elif facts:
        normalized["facts"] = [_normalize_fact_payload(facts, resume_text)]
    else:
        normalized["facts"] = []

    normalized["question_chain"] = _normalize_question_chain(
        normalized.get("question_chain", []),
    )

    missing_information = normalized.get("missing_information", [])
    if isinstance(missing_information, list):
        normalized["missing_information"] = [
            _model_value_to_text(item) for item in missing_information
        ]
    elif missing_information:
        normalized["missing_information"] = [_model_value_to_text(missing_information)]
    else:
        normalized["missing_information"] = []

    return normalized


def parse_model_analysis(content: str) -> AgentProjectAnalysisResponse:
    try:
        payload = normalize_project_analysis_payload(
            parse_model_json(content),
            "",
        )
        return AgentProjectAnalysisResponse.model_validate(payload)
    except ModelOutputError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("model returned invalid project analysis JSON") from exc


def validate_analysis_evidence(
    result: AgentProjectAnalysisResponse,
    resume_text: str,
) -> AgentProjectAnalysisResponse:
    for evidence in result.evidence:
        if evidence.quote not in resume_text:
            raise ValueError("analysis evidence was not found in resume text")

    normalized = normalize_project_analysis_payload(
        result.model_dump(),
        resume_text,
    )
    return AgentProjectAnalysisResponse.model_validate(normalized)
