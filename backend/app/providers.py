from dataclasses import dataclass
import hashlib
import json
import time
from collections.abc import Sequence
from typing import Protocol

import httpx

from .project_analysis import (
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_model_analysis,
)
from .model_output import ModelOutputError, content_to_text, parse_model_json
from .model_settings import ModelSettingsValues
from .prompts import (
    DIALOG_QUESTION_MAX_CHARS,
    INTERVIEWER_SYSTEM_PROMPT,
    ASSESSMENT_PROMPT_VERSION,
    ASSESSMENT_SYSTEM_PROMPT,
    CONFIDENCE_SEMANTICS,
    FEEDBACK_SYSTEM_PROMPT,
    FEEDBACK_CONTENT_MAX_CHARS,
    FEEDBACK_HINT_MAX_CHARS,
    FEEDBACK_HINT_COUNT,
    FOLLOWUP_SYSTEM_PROMPT,
    OFFTOPIC_RULE,
    PERSONA_SYSTEM_PROMPTS,
    VERIFIER_SYSTEM_PROMPT,
    WIKI_SYSTEM_PROMPT,
    render_level_anchors,
)
from .question_bank import QuestionSpec
from .rubrics import build_rubric
from .schemas import AgentProjectAnalysisResponse
from .llm_observability import ModelCallRecord, emit_model_call
from .models import utc_now


@dataclass(frozen=True, slots=True)
class RubricAssessmentResult:
    rubric_id: str
    level: int
    evidence_start: int
    evidence_end: int
    quoted_text: str
    answer_text_hash: str
    confidence: float
    validity: str = "valid"
    invalid_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    level: int
    evidence_start: int
    evidence_end: int
    quoted_text: str
    answer_text_hash: str
    gaps: tuple[str, ...]
    confidence: float
    rubric_items: tuple[RubricAssessmentResult, ...] = ()
    evaluator: str = "alpha-local-rule-v1"


@dataclass(frozen=True, slots=True)
class BatchAssessmentCase:
    answer_id: str
    question_id: str
    question: QuestionSpec
    answer_text: str
    followup_question: str = ""
    followup_text: str = ""
    # 模型回传用的短关联 ID（如 "c1"），程序侧映射回真 ID，避免模型抄写长 UUID 出错
    case_ref: str = ""


@dataclass(frozen=True, slots=True)
class BatchAssessmentItem:
    answer_id: str
    question_id: str
    result: AssessmentResult
    commentary: str = ""


class AssessmentProvider(Protocol):
    def assess_batch(
        self, cases: Sequence[BatchAssessmentCase]
    ) -> tuple[BatchAssessmentItem, ...]:
        ...


@dataclass(frozen=True, slots=True)
class FollowupDecision:
    should_followup: bool
    reason: str = ""
    followup_question: str = ""


class FollowupDecisionProvider(Protocol):
    def decide_followup(
        self,
        question_prompt: str,
        rubric_items: Sequence[dict],
        answer_text: str,
        prepared_followups: Sequence[str],
        previous_followups: Sequence[dict] = (),
        persona: str = "standard",
    ) -> FollowupDecision:
        ...


@dataclass(frozen=True, slots=True)
class PracticeFeedback:
    content: str
    focus_hints: tuple[str, ...] = ()


class PracticeFeedbackProvider(Protocol):
    def feedback_for_answer(
        self,
        question_prompt: str,
        answer_text: str,
        reference_facts: Sequence[str] = (),
    ) -> PracticeFeedback:
        ...


class ProjectAnalysisProvider(Protocol):
    def analyze(self, resume_text: str) -> AgentProjectAnalysisResponse:
        ...


class ProjectAnalysisProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AssessmentProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AssessmentResponseError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def map_provider_http_error(status_code: int, error_cls):
    if status_code in (401, 403):
        return error_cls("provider_auth_failed", "模型服务认证失败", status_code)
    if status_code == 429:
        return error_cls("provider_rate_limited", "模型服务请求过于频繁，请稍后重试", status_code)
    if status_code in {502, 503, 504}:
        return error_cls("provider_unavailable", "模型服务暂时不可用，请稍后重试", status_code)
    return error_cls("provider_http_error", "模型服务请求失败，请稍后重试", status_code)


def _extract_usage(response: httpx.Response) -> dict:
    """Best-effort token usage from the provider envelope; advisory only."""
    try:
        usage = (response.json() or {}).get("usage") or {}
    except (TypeError, ValueError):
        return {}
    return {
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        "completion_tokens": usage.get("completion_tokens") or 0,
    }


def _extract_model_content(response: httpx.Response, error_type):
    """Validate the provider envelope before handing content to a parser."""
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise error_type("invalid_model_response", "模型服务响应不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise error_type("invalid_model_response", "模型服务响应结构异常")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise error_type("invalid_model_response", "模型服务响应缺少 choices")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise error_type("provider_output_truncated", "模型输出达到长度上限，内容不完整")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise error_type("invalid_model_response", "模型服务响应缺少 message")
    content = message.get("content")
    if not content_to_text(content).strip():
        raise error_type("empty_model_response", "模型没有返回可解析内容")
    return content


def probe_model_connection(
    settings: ModelSettingsValues,
    client: httpx.Client | None = None,
) -> dict:
    started_at = time.perf_counter()
    base_result = {
        "ok": False,
        "message": "",
        "model": settings.model,
        "latency_ms": 0,
        "error_code": None,
    }
    if not settings.api_key:
        base_result["message"] = "模型服务尚未配置 API Key"
        base_result["error_code"] = "provider_not_configured"
        return base_result

    provider = SiliconFlowAssessmentProvider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        client=client,
    )
    payload = {
        "model": settings.model,
        "temperature": settings.temperature,
        "max_tokens": 16,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "只返回合法 JSON。"},
            {"role": "user", "content": "返回 {\"ok\":true}。"},
        ],
    }
    try:
        response = provider._request(payload)
        response.raise_for_status()
        content = _extract_model_content(response, AssessmentProviderError)
        parsed = parse_model_json(content)
        if not isinstance(parsed, dict):
            raise AssessmentProviderError("invalid_model_response", "模型测试返回结构异常")
        base_result["ok"] = True
        base_result["message"] = "模型连接正常"
    except httpx.TimeoutException:
        base_result["message"] = "模型请求超时"
        base_result["error_code"] = "provider_timeout"
    except httpx.HTTPStatusError as exc:
        error = map_provider_http_error(exc.response.status_code, AssessmentProviderError)
        base_result["message"] = str(error)
        base_result["error_code"] = error.code
    except httpx.RequestError:
        base_result["message"] = "无法连接模型服务"
        base_result["error_code"] = "provider_connection_failed"
    except AssessmentProviderError as exc:
        base_result["message"] = str(exc)
        base_result["error_code"] = exc.code
    except ModelOutputError as exc:
        base_result["message"] = str(exc)
        base_result["error_code"] = "invalid_model_response"
    finally:
        base_result["latency_ms"] = max(
            0,
            int((time.perf_counter() - started_at) * 1000),
        )
    return base_result


FOLLOWUP_QUESTION_MAX_CHARS = 300


def build_followup_decision_prompt(
    question_prompt: str,
    rubric_items: Sequence[dict],
    answer_text: str,
    prepared_followups: Sequence[str],
    previous_followups: Sequence[dict] = (),
    persona: str = "standard",
) -> tuple[str, str]:
    user_payload = {
        "question": question_prompt,
        "rubric_items": [
            {
                "rubric_id": item.get("rubric_id"),
                "criterion": item.get("criterion"),
            }
            for item in rubric_items
        ],
        "answer": answer_text,
        "prepared_followups": list(prepared_followups),
        "previous_followups": list(previous_followups),
    }
    user_prompt = (
        "判断这个回答是否触发了值得追问的信号：回答明显不完整（incomplete）、"
        "与题目要求存在矛盾或含糊（conflicting），或存在值得深挖的关键点（probe）。"
        "回答已经足够完整清楚时不要追问。previous_followups 是已经问过的追问和候选人的回答："
        "如果里面的回答仍含糊或引出新疑点，可以继续往深处追问一层；已经清楚则收束。"
        "追问必须聚焦当前问题本身，长度不超过 300 字符。"
        "prepared_followups 是可用的预备追问，可以原样采用、改写，"
        "也可以给出更合适的新追问。输出格式必须为 "
        '{"should_followup": true|false, "reason": "incomplete|conflicting|probe", '
        '"followup_question": "..."}，不追问时 followup_question 为空字符串，'
        "不要添加其他字段。" + chr(10)
        + json.dumps(user_payload, ensure_ascii=False)
    )
    return PERSONA_SYSTEM_PROMPTS.get(persona, FOLLOWUP_SYSTEM_PROMPT), user_prompt


def parse_followup_decision(content: object) -> FollowupDecision:
    try:
        payload = parse_model_json(content)
    except ModelOutputError as exc:
        raise AssessmentProviderError(exc.code, str(exc)) from exc

    if not isinstance(payload, dict):
        raise AssessmentProviderError("invalid_model_response", "追问决策返回必须是 JSON 对象")
    allowed_keys = {"should_followup", "reason", "followup_question"}
    if set(payload) - allowed_keys:
        raise AssessmentProviderError(
            "invalid_model_response", "追问决策返回包含未允许的字段"
        )
    should_followup = payload.get("should_followup")
    if not isinstance(should_followup, bool):
        raise AssessmentProviderError(
            "invalid_model_response", "追问决策缺少 should_followup 布尔值"
        )
    if not should_followup:
        return FollowupDecision(should_followup=False)
    question = payload.get("followup_question")
    if not isinstance(question, str) or not question.strip():
        raise AssessmentProviderError(
            "invalid_model_response", "追问决策缺少 followup_question"
        )
    reason = payload.get("reason")
    reason_value = reason if reason in FOLLOWUP_REASON_VALUES else "probe"
    return FollowupDecision(
        should_followup=True,
        reason=reason_value,
        followup_question=" ".join(question.split())[:FOLLOWUP_QUESTION_MAX_CHARS],
    )


def build_feedback_prompt(
    question_prompt: str,
    answer_text: str,
    reference_facts: Sequence[str] = (),
) -> tuple[str, str]:
    user_payload = {
        "question": question_prompt,
        "answer": answer_text,
        "reference_facts": list(reference_facts),
    }
    user_prompt = (
        "请点评这个回答：先肯定答到的点，再指出最值得补的一两处，最后给一条可执行的练习建议。"
        "reference_facts 是这道题的标准答题要点，点评时对照它们指出回答漏掉了哪些要点，"
        "用面试官的语言描述，不要出现'参考事实'这个词。"
        "语气自然、面向练习者，不要罗列所有问题。输出格式必须为 "
        '{"content": "点评正文（不超过 500 字）", "focus_hints": ["如果面试官继续挖，可能会问的一个方向", "..."]}'
        "，focus_hints 最多 3 条，不要添加其他字段。" + chr(10)
        + json.dumps(user_payload, ensure_ascii=False)
    )
    return FEEDBACK_SYSTEM_PROMPT, user_prompt


def parse_feedback(content: object) -> PracticeFeedback:
    try:
        payload = parse_model_json(content)
    except ModelOutputError as exc:
        raise AssessmentProviderError(exc.code, str(exc)) from exc

    if not isinstance(payload, dict):
        raise AssessmentProviderError("invalid_model_response", "练习反馈返回必须是 JSON 对象")
    text = payload.get("content")
    if not isinstance(text, str) or not text.strip():
        raise AssessmentProviderError("invalid_model_response", "练习反馈缺少 content")
    raw_hints = payload.get("focus_hints", [])
    if not isinstance(raw_hints, list):
        raw_hints = []
    hints = tuple(
        " ".join(str(hint).split())[:FEEDBACK_HINT_MAX_CHARS]
        for hint in raw_hints
        if isinstance(hint, str) and hint.strip()
    )[:FEEDBACK_HINT_COUNT]
    return PracticeFeedback(
        content=" ".join(text.split())[:FEEDBACK_CONTENT_MAX_CHARS],
        focus_hints=hints,
    )


def build_assessment_prompt(question: QuestionSpec, rubric, answer_text: str) -> tuple[str, str]:
    user_payload = {
        "question": question.prompt,
        "category": question.category,
        "knowledge_point_id": question.knowledge_point_id,
        "rubric_version": rubric.version,
        "rubric_items": [
            {
                "rubric_id": item.rubric_id,
                "criterion": item.criterion,
                "reference_facts": list(item.reference_facts),
            }
            for item in rubric.items
        ],
        "reference_facts": list(rubric.reference_facts),
        "answer": answer_text,
    }
    user_prompt = (
        "评分前先逐条对照以下等级锚点，再判断每个 Rubric 项的 level：\n"
        + render_level_anchors()
        + "\n"
        + CONFIDENCE_SEMANTICS
        + "\n"
        + OFFTOPIC_RULE
        + "\n请对每个 Rubric 项输出 level、quoted_text 和 confidence。"
        "level 只能是 0 到 4 的整数，confidence 只能是 0 到 1 的数字。"
        "quoted_text 必须逐字摘自当前回答；不要输出 evidence_start、evidence_end 或 answer_text_hash，"
        "这些字段由程序根据回答原文生成。"
        "输出格式必须为 {\"items\":[...]}，不要添加其他字段。\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )
    return ASSESSMENT_SYSTEM_PROMPT, user_prompt


def _case_payload(case: BatchAssessmentCase) -> dict:
    rubric = build_rubric(case.question)
    payload = {
        "case_id": case.case_ref,
        "question": case.question.prompt,
        "category": case.question.category,
        "knowledge_point_id": case.question.knowledge_point_id,
        "rubric_version": rubric.version,
        "rubric_items": [
            {
                "rubric_id": item.rubric_id,
                "criterion": item.criterion,
                "reference_facts": list(item.reference_facts),
            }
            for item in rubric.items
        ],
        "reference_facts": list(rubric.reference_facts),
        "answer": case.answer_text,
    }
    if case.followup_text:
        payload["followup"] = {
            "question": case.followup_question,
            "answer": case.followup_text,
        }
    return payload


def build_batch_assessment_prompt(
    cases: Sequence[BatchAssessmentCase],
) -> tuple[str, str]:
    user_payload = {"cases": [_case_payload(case) for case in cases]}
    user_prompt = (
        "评分前先逐条对照以下等级锚点，再判断每个 case 的 Rubric 项 level：\n"
        + render_level_anchors()
        + "\n"
        + CONFIDENCE_SEMANTICS
        + "\n"
        + OFFTOPIC_RULE
        + "\n请把每个 case 视为完全独立的评分任务，逐题输出全部 Rubric 项。"
        "不要比较 case，不要补充输入中没有的信息。每个 Rubric 项输出 level、"
        "quoted_text 和 confidence。level 只能是 0 到 4 的整数，"
        "confidence 只能是 0 到 1 的数字。"
        "有 followup 字段时，追问回答与首答共同构成该题的完整回答，综合评分，"
        "不因回答被追问过本身而扣分；quoted_text 必须逐字摘自首答或追问回答之一。"
        "输出格式必须为 "
        '{"items":[{"case_id":"...","rubric_items":[...],"comment":"..."}]}'
        "。case_id 必须逐字原样返回输入里的 case_id，不要改写。"
        "每个 case 输出一个 comment 字段：不超过 80 字，说明这道题为什么是这个等级，"
        "必须落到这个回答的具体内容上，不要空泛。"
        "不要输出 evidence_start、evidence_end 或 answer_text_hash，这些字段由程序生成。"
        "除 case_id 和 comment 外不要添加其他字段。\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )
    return ASSESSMENT_SYSTEM_PROMPT, user_prompt


class _SiliconFlowClient:
    """硅基浮点兼容 chat 接口的公共客户端：请求、payload 组装与统一异常梯子。"""

    error_cls: type[Exception] = AssessmentProviderError

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        temperature: float = 0.1,
        max_tokens: int = 800,
        client: httpx.Client | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = client

    def _require_api_key(self) -> None:
        if not self._api_key:
            raise self.error_cls("provider_not_configured", "模型服务尚未配置")

    @property
    def model_name(self) -> str:
        return self._model

    def _request(self, payload: dict) -> httpx.Response:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            return self._client.post(url, headers=headers, json=payload, timeout=self._timeout)
        with httpx.Client(timeout=self._timeout) as client:
            return client.post(url, headers=headers, json=payload)

    def _payload(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        disable_thinking: bool = False,
        json_mode: bool = True,
    ) -> dict:
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if disable_thinking:
            payload["enable_thinking"] = False
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _chat(self, payload: dict, parse, *, call_kind: str, prompt_version: str | None = None):
        started = time.perf_counter()
        started_at = None
        response = None
        error_code = None
        try:
            response = self._request(payload)
            response.raise_for_status()
            content = _extract_model_content(response, self.error_cls)
            return parse(content)
        except httpx.TimeoutException as exc:
            error_code = "provider_timeout"
            raise self.error_cls("provider_timeout", "模型请求超时") from exc
        except httpx.HTTPStatusError as exc:
            mapped = map_provider_http_error(exc.response.status_code, self.error_cls)
            error_code = mapped.code
            raise mapped from exc
        except httpx.RequestError as exc:
            error_code = "provider_connection_failed"
            raise self.error_cls("provider_connection_failed", "无法连接模型服务") from exc
        except self.error_cls as exc:
            error_code = exc.code
            raise
        except ModelOutputError as exc:
            error_code = exc.code
            raise self.error_cls(exc.code, str(exc)) from exc
        except AssessmentResponseError as exc:
            error_code = exc.code
            raise self.error_cls(exc.code, str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            error_code = "invalid_model_response"
            raise self.error_cls("invalid_model_response", "模型返回格式异常") from exc
        finally:
            usage = _extract_usage(response) if response is not None else {}
            now = utc_now()
            emit_model_call(ModelCallRecord(
                trace_id="", call_kind=call_kind, provider="siliconflow", model_name=self._model,
                prompt_version=prompt_version, status="failed" if error_code else "succeeded",
                error_code=error_code, input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"), latency_ms=round((time.perf_counter() - started) * 1000),
                request_bytes=len(json.dumps(payload, ensure_ascii=False).encode()),
                response_bytes=len(response.content) if response is not None else None,
                created_at=now, finished_at=now,
            ))

    def chat_json(self, system_prompt: str, user_prompt: str, parse, *,
                  call_kind: str, prompt_version: str | None = None):
        """Public JSON call seam for role-specific interview agents."""
        self._require_api_key()
        return self._chat(
            self._payload(system_prompt, user_prompt, disable_thinking=True),
            parse,
            call_kind=call_kind,
            prompt_version=prompt_version,
        )


class SiliconFlowProjectAnalysisProvider(_SiliconFlowClient):
    error_cls = ProjectAnalysisProviderError

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        temperature: float = 0.1,
        max_tokens: int = 3200,
        client: httpx.Client | None = None,
    ):
        super().__init__(
            api_key,
            model,
            base_url,
            timeout_seconds,
            temperature,
            max_tokens,
            client,
        )

    def analyze(self, resume_text: str) -> AgentProjectAnalysisResponse:
        self._require_api_key()
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "thinking_budget": 256,
            "reasoning_effort": "high",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(resume_text)},
            ],
        }
        return self._chat(payload, parse_model_analysis, call_kind="project_analysis")


class SiliconFlowFollowupProvider(_SiliconFlowClient):
    """Decides whether a submitted answer deserves one follow-up question."""

    def decide_followup(
        self,
        question_prompt: str,
        rubric_items: Sequence[dict],
        answer_text: str,
        prepared_followups: Sequence[str],
        previous_followups: Sequence[dict] = (),
        persona: str = "standard",
    ) -> FollowupDecision:
        self._require_api_key()
        system_prompt, user_prompt = build_followup_decision_prompt(
            question_prompt,
            rubric_items,
            answer_text,
            prepared_followups,
            previous_followups,
            persona,
        )
        return self._chat(
            self._payload(system_prompt, user_prompt, disable_thinking=True),
            parse_followup_decision,
            call_kind="followup_decision",
        )

    def generate_interviewer_turn(self, payload: dict) -> dict:
        self._require_api_key()
        system_prompt, user_prompt = build_interviewer_prompt(payload)
        # 交互类调用：关闭思考，实测省 ~30% 延迟
        return self._chat(
            self._payload(system_prompt, user_prompt, disable_thinking=True),
            parse_interviewer_turn,
            call_kind="dialog_turn",
        )

    def feedback_for_answer(
        self,
        question_prompt: str,
        answer_text: str,
        reference_facts: Sequence[str] = (),
    ) -> PracticeFeedback:
        self._require_api_key()
        system_prompt, user_prompt = build_feedback_prompt(
            question_prompt, answer_text, reference_facts
        )
        return self._chat(
            self._payload(system_prompt, user_prompt, disable_thinking=True),
            parse_feedback,
            call_kind="practice_feedback",
        )


def build_wiki_prompt(payload: dict) -> tuple[str, str]:
    user_prompt = (
        "请为这个知识点生成深度讲解。mechanism 是机制详解（300-500 字，讲清怎么工作、"
        "为什么这样设计）；personal_focus 是针对候选人最近回答的个性化提示（不超过 100 字，"
        "指出他上次漏了什么、这次该补什么；没有最近回答时给最常见的学习建议）；"
        "pitfalls_extra 是讲解中发现的额外常见误区（0-3 条，每条一句话），"
        "注意 payload 里的 already_covered 是页面上已有的内容，不要与它重复。"
        '输出格式必须为 {"mechanism":"...","personal_focus":"...","pitfalls_extra":["..."]}'
        "，不要添加其他字段。" + chr(10)
        + json.dumps(payload, ensure_ascii=False)
    )
    return WIKI_SYSTEM_PROMPT, user_prompt


def parse_wiki_response(content: object) -> dict:
    try:
        payload = parse_model_json(content)
    except ModelOutputError as exc:
        raise AssessmentProviderError(exc.code, str(exc)) from exc
    if not isinstance(payload, dict):
        raise AssessmentProviderError("invalid_model_response", "深讲返回必须是 JSON 对象")
    mechanism = payload.get("mechanism")
    if not isinstance(mechanism, str) or not mechanism.strip():
        raise AssessmentProviderError("invalid_model_response", "深讲缺少 mechanism")
    personal = payload.get("personal_focus", "")
    raw_pitfalls = payload.get("pitfalls_extra", [])
    return {
        "mechanism": " ".join(mechanism.split())[:2000],
        "personal_focus": " ".join(str(personal).split())[:300] if isinstance(personal, str) else "",
        "pitfalls_extra": [
            " ".join(str(p).split())[:200]
            for p in (raw_pitfalls if isinstance(raw_pitfalls, list) else [])
            if isinstance(p, str) and p.strip()
        ][:3],
    }


def build_interviewer_prompt(payload: dict) -> tuple[str, str]:
    user_prompt = (
        "基于对话历史和项目事实，输出你的下一句追问。"
        "question 要引用候选人上一轮回答里的具体内容；"
        "如果项目关键信息（背景、职责、方案、取舍、验证、结果）都已挖到，"
        "且已问轮数达到下限，输出 saturated=true 并给收束语；否则 saturated=false。"
        "只问一个问题，不要一次抛出多个。"
        '输出格式必须为 {"question":"...","saturated":true|false}，不要添加其他字段。'
        + chr(10)
        + json.dumps(payload, ensure_ascii=False)
    )
    return INTERVIEWER_SYSTEM_PROMPT, user_prompt


def parse_interviewer_turn(content: object) -> dict:
    try:
        payload = parse_model_json(content)
    except ModelOutputError as exc:
        raise AssessmentProviderError(exc.code, str(exc)) from exc
    if not isinstance(payload, dict):
        raise AssessmentProviderError("invalid_model_response", "面试官返回必须是 JSON 对象")
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise AssessmentProviderError("invalid_model_response", "面试官返回缺少 question")
    return {
        "question": " ".join(question.split())[: DIALOG_QUESTION_MAX_CHARS],
        "saturated": bool(payload.get("saturated", False)),
    }


def build_verifier_prompt(entries: Sequence[dict]) -> tuple[str, str]:
    """entries: [{rubric_id, criterion, quoted_text, level, question, answer}]"""
    user_payload = {"observations": list(entries)}
    user_prompt = (
        "判断引用是否支持该等级时，对照以下等级锚点：\n"
        + render_level_anchors()
        + "\n对每条观察输出判断：quote_relevant（引用是否与考察点相关）、"
        "level_supported（引用是否支持该等级，拿不准时为 true）、"
        "仅在 level_supported 为 false 且你认为等级偏差达到 2 级以上时给出 suggested_level（0-4 整数）。"
        '输出格式必须为 {"items":[{"rubric_id":"...","quote_relevant":true|false,'
        '"level_supported":true|false,"suggested_level":null|0-4}]}，items 与输入一一对应，'
        "不要添加其他字段。" + chr(10)
        + json.dumps(user_payload, ensure_ascii=False)
    )
    return VERIFIER_SYSTEM_PROMPT, user_prompt


def parse_verifier_response(content: object) -> dict[str, dict]:
    try:
        payload = parse_model_json(content)
    except ModelOutputError as exc:
        raise AssessmentProviderError(exc.code, str(exc)) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise AssessmentProviderError("invalid_model_response", "复核返回必须是 JSON 对象")
    verdicts: dict[str, dict] = {}
    for raw in payload["items"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("rubric_id"), str):
            continue
        verdicts[raw["rubric_id"]] = {
            "quote_relevant": bool(raw.get("quote_relevant", True)),
            "level_supported": bool(raw.get("level_supported", True)),
            "suggested_level": raw.get("suggested_level")
            if isinstance(raw.get("suggested_level"), int)
            else None,
        }
    # 复核缺项按"无分歧"处理，不阻塞主评分
    return verdicts


class SiliconFlowAssessmentProvider(_SiliconFlowClient):
    evaluator = "siliconflow-blind-rubric-v1"
    prompt_version = ASSESSMENT_PROMPT_VERSION

    def assess(
        self, question: QuestionSpec, answer_text: str, status: str
    ) -> AssessmentResult:
        from .assessment_engine import (
            aggregate_assessment,
            parse_model_assessment,
        )

        if status not in {"submitted", "explicit_unknown"}:
            raise ValueError("status must be submitted or explicit_unknown")
        if status == "submitted" and not answer_text.strip():
            raise ValueError("answer_text cannot be blank for submitted status")
        self._require_api_key()

        rubric = build_rubric(question)
        system_prompt, user_prompt = build_assessment_prompt(question, rubric, answer_text)

        def _assess(content: str) -> AssessmentResult:
            items = parse_model_assessment(content, rubric, answer_text)
            return aggregate_assessment(question, answer_text, items, self.evaluator)

        return self._chat(
            self._payload(system_prompt, user_prompt, json_mode=False),
            _assess,
            call_kind="assessment",
            prompt_version=ASSESSMENT_PROMPT_VERSION,
        )

    def generate_skill_wiki(self, payload: dict) -> dict:
        self._require_api_key()
        system_prompt, user_prompt = build_wiki_prompt(payload)
        return self._chat(self._payload(system_prompt, user_prompt), parse_wiki_response, call_kind="skill_wiki")

    def verify_batch(self, entries: Sequence[dict]) -> dict[str, dict]:
        """entries 按 rubric_id 分组前先带 case 维度；返回 {rubric_id: verdict}。

        多 case 同 rubric_id 时由调用方逐批拆分（每批一个 case）。
        """
        if not entries:
            return {}
        self._require_api_key()
        system_prompt, user_prompt = build_verifier_prompt(entries)
        return self._chat(
            self._payload(system_prompt, user_prompt),
            parse_verifier_response,
            call_kind="assessment_verify",
        )

    def assess_batch(
        self, cases: Sequence[BatchAssessmentCase]
    ) -> tuple[BatchAssessmentItem, ...]:
        from .assessment_engine import (
            parse_batch_model_assessment,
        )

        if not cases:
            return ()
        self._require_api_key()
        system_prompt, user_prompt = build_batch_assessment_prompt(cases)
        return self._chat(
            self._payload(system_prompt, user_prompt),
            lambda content: parse_batch_model_assessment(content, cases, self.evaluator),
            call_kind="assessment_batch",
            prompt_version=ASSESSMENT_PROMPT_VERSION,
        )


class RuleBasedAssessmentProvider:
    """Deterministic local evaluator used until a model Provider is added."""

    evaluator = "alpha-local-rule-v1"

    _KNOWN_STATUSES = {"submitted", "explicit_unknown"}
    _DEPTH_TERMS = ("机制", "边界", "取舍", "权衡", "监控", "失败", "降级", "trade-off")

    def assess(
        self, question: QuestionSpec, answer_text: str, status: str
    ) -> AssessmentResult:
        if status not in self._KNOWN_STATUSES:
            raise ValueError("status must be submitted or explicit_unknown")

        if status == "submitted" and not answer_text.strip():
            raise ValueError("answer_text cannot be blank for submitted status")

        answer_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
        if status == "explicit_unknown":
            return AssessmentResult(
                level=0,
                evidence_start=0,
                evidence_end=len(answer_text),
                quoted_text=answer_text,
                answer_text_hash=answer_hash,
                gaps=question.signals,
                confidence=0.9,
            )

        matched_signals = tuple(
            signal for signal in question.signals if signal.lower() in answer_text.lower()
        )
        level = 0
        if len(answer_text.strip()) >= 15:
            level += 1
        if matched_signals:
            level += 1
        if len(matched_signals) >= 2:
            level += 1
        if len(matched_signals) >= 3 or any(
            term in answer_text.lower() for term in self._DEPTH_TERMS
        ):
            level += 1
        level = min(4, level)

        confidence = min(
            0.95,
            round(0.45 + (0.08 * len(matched_signals)) + (0.02 if len(answer_text) >= 60 else 0), 2),
        )
        gaps = tuple(signal for signal in question.signals if signal not in matched_signals)
        return AssessmentResult(
            level=level,
            evidence_start=0,
            evidence_end=len(answer_text),
            quoted_text=answer_text,
            answer_text_hash=answer_hash,
            gaps=gaps,
            confidence=confidence,
        )
