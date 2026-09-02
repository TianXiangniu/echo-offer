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
from .question_bank import QuestionSpec
from .rubrics import build_rubric
from .schemas import AgentProjectAnalysisResponse


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


@dataclass(frozen=True, slots=True)
class BatchAssessmentItem:
    answer_id: str
    question_id: str
    result: AssessmentResult


class AssessmentProvider(Protocol):
    def assess_batch(
        self, cases: Sequence[BatchAssessmentCase]
    ) -> tuple[BatchAssessmentItem, ...]:
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


def map_provider_http_error(status_code: int) -> ProjectAnalysisProviderError:
    if status_code == 401 or status_code == 403:
        return ProjectAnalysisProviderError(
            "provider_auth_failed", "模型服务认证失败", status_code
        )
    if status_code == 429:
        return ProjectAnalysisProviderError(
            "provider_rate_limited", "模型服务请求过于频繁，请稍后重试", status_code
        )
    if status_code in {502, 503, 504}:
        return ProjectAnalysisProviderError(
            "provider_unavailable", "模型服务暂时不可用，请稍后重试", status_code
        )
    return ProjectAnalysisProviderError(
        "provider_http_error", "模型服务请求失败，请稍后重试", status_code
    )


def map_assessment_http_error(status_code: int) -> AssessmentProviderError:
    if status_code == 401 or status_code == 403:
        return AssessmentProviderError("provider_auth_failed", "模型服务认证失败", status_code)
    if status_code == 429:
        return AssessmentProviderError(
            "provider_rate_limited", "模型服务请求过于频繁，请稍后重试", status_code
        )
    if status_code in {502, 503, 504}:
        return AssessmentProviderError(
            "provider_unavailable", "模型服务暂时不可用，请稍后重试", status_code
        )
    return AssessmentProviderError(
        "provider_http_error", "模型服务请求失败，请稍后重试", status_code
    )


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
        error = map_assessment_http_error(exc.response.status_code)
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


ASSESSMENT_SYSTEM_PROMPT = (
    "你是一个盲评分器。你只能依据当前问题、冻结 Rubric、允许的参考事实和当前回答进行判断。"
    "不要推断未提供的信息，只评估每个 Rubric 项。必须只返回合法 JSON。"
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
        "answer": answer_text,
    }
    user_prompt = (
        "请对每个 Rubric 项输出 level、quoted_text 和 confidence。"
        "level 只能是 0 到 4 的整数，confidence 只能是 0 到 1 的数字。"
        "quoted_text 必须逐字摘自当前回答；不要输出 evidence_start、evidence_end 或 answer_text_hash，"
        "这些字段由程序根据回答原文生成。"
        "输出格式必须为 {\"items\":[...]}，不要添加其他字段。\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )
    return ASSESSMENT_SYSTEM_PROMPT, user_prompt


def build_batch_assessment_prompt(
    cases: Sequence[BatchAssessmentCase],
) -> tuple[str, str]:
    user_payload = {
        "cases": [
            {
                "answer_id": case.answer_id,
                "question_id": case.question_id,
                "question": case.question.prompt,
                "category": case.question.category,
                "knowledge_point_id": case.question.knowledge_point_id,
                "rubric_version": build_rubric(case.question).version,
                "rubric_items": [
                    {
                        "rubric_id": item.rubric_id,
                        "criterion": item.criterion,
                        "reference_facts": list(item.reference_facts),
                    }
                    for item in build_rubric(case.question).items
                ],
                "answer": case.answer_text,
            }
            for case in cases
        ]
    }
    user_prompt = (
        "请把每个 case 视为完全独立的评分任务，逐题输出全部 Rubric 项。"
        "不要比较 case，不要补充输入中没有的信息。每个 Rubric 项输出 level、"
        "quoted_text 和 confidence。level 只能是 0 到 4 的整数，"
        "confidence 只能是 0 到 1 的数字。输出格式必须为 "
        '{"items":[{"answer_id":"...","question_id":"...","rubric_items":[...]}]}'
        "。不要输出 evidence_start、evidence_end 或 answer_text_hash，这些字段由程序生成。"
        "不要添加其他字段。\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )
    return ASSESSMENT_SYSTEM_PROMPT, user_prompt


class SiliconFlowProjectAnalysisProvider:
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
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = client

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

    def analyze(self, resume_text: str) -> AgentProjectAnalysisResponse:
        if not self._api_key:
            raise ProjectAnalysisProviderError("provider_not_configured", "模型服务尚未配置")
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
        try:
            response = self._request(payload)
            response.raise_for_status()
            content = _extract_model_content(response, ProjectAnalysisProviderError)
            return parse_model_analysis(content)
        except httpx.TimeoutException as exc:
            raise ProjectAnalysisProviderError("provider_timeout", "模型请求超时") from exc
        except httpx.HTTPStatusError as exc:
            raise map_provider_http_error(exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise ProjectAnalysisProviderError("provider_connection_failed", "无法连接模型服务") from exc
        except ModelOutputError as exc:
            raise ProjectAnalysisProviderError(exc.code, str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectAnalysisProviderError("invalid_model_response", "模型返回格式异常") from exc


class SiliconFlowAssessmentProvider:
    evaluator = "siliconflow-blind-rubric-v1"

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
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = client

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

    def assess(
        self, question: QuestionSpec, answer_text: str, status: str
    ) -> AssessmentResult:
        from .assessment_engine import (
            AssessmentResponseError,
            aggregate_assessment,
            parse_model_assessment,
        )

        if status not in {"submitted", "explicit_unknown"}:
            raise ValueError("status must be submitted or explicit_unknown")
        if status == "submitted" and not answer_text.strip():
            raise ValueError("answer_text cannot be blank for submitted status")
        if not self._api_key:
            raise AssessmentProviderError("provider_not_configured", "模型服务尚未配置")

        rubric = build_rubric(question)
        system_prompt, user_prompt = build_assessment_prompt(question, rubric, answer_text)
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = self._request(payload)
            response.raise_for_status()
            content = _extract_model_content(response, AssessmentProviderError)
            items = parse_model_assessment(content, rubric, answer_text)
            return aggregate_assessment(question, answer_text, items, self.evaluator)
        except httpx.TimeoutException as exc:
            raise AssessmentProviderError("provider_timeout", "模型请求超时") from exc
        except httpx.HTTPStatusError as exc:
            raise map_assessment_http_error(exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise AssessmentProviderError(
                "provider_connection_failed", "无法连接模型服务"
            ) from exc
        except AssessmentResponseError as exc:
            raise AssessmentProviderError(exc.code, str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise AssessmentProviderError("invalid_model_response", "模型返回格式异常") from exc

    def assess_batch(
        self, cases: Sequence[BatchAssessmentCase]
    ) -> tuple[BatchAssessmentItem, ...]:
        from .assessment_engine import (
            AssessmentResponseError,
            parse_batch_model_assessment,
        )

        if not cases:
            return ()
        if not self._api_key:
            raise AssessmentProviderError("provider_not_configured", "模型服务尚未配置")
        system_prompt, user_prompt = build_batch_assessment_prompt(cases)
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = self._request(payload)
            response.raise_for_status()
            content = _extract_model_content(response, AssessmentProviderError)
            return parse_batch_model_assessment(content, cases, self.evaluator)
        except httpx.TimeoutException as exc:
            raise AssessmentProviderError("provider_timeout", "模型请求超时") from exc
        except httpx.HTTPStatusError as exc:
            raise map_assessment_http_error(exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise AssessmentProviderError(
                "provider_connection_failed", "无法连接模型服务"
            ) from exc
        except AssessmentProviderError:
            raise
        except AssessmentResponseError as exc:
            raise AssessmentProviderError(exc.code, str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise AssessmentProviderError("invalid_model_response", "模型返回格式异常") from exc


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
