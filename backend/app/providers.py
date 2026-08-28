from dataclasses import dataclass
import hashlib
from typing import Protocol

import httpx

from .project_analysis import (
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_model_analysis,
)
from .question_bank import QuestionSpec
from .schemas import AgentProjectAnalysisResponse


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    level: int
    evidence_start: int
    evidence_end: int
    quoted_text: str
    answer_text_hash: str
    gaps: tuple[str, ...]
    confidence: float


class AssessmentProvider(Protocol):
    def assess(
        self, question: QuestionSpec, answer_text: str, status: str
    ) -> AssessmentResult:
        ...


class ProjectAnalysisProvider(Protocol):
    def analyze(self, resume_text: str) -> AgentProjectAnalysisResponse:
        ...


class ProjectAnalysisProviderError(Exception):
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


class SiliconFlowProjectAnalysisProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
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
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(resume_text)},
            ],
        }
        try:
            response = self._request(payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return parse_model_analysis(content)
        except httpx.TimeoutException as exc:
            raise ProjectAnalysisProviderError("provider_timeout", "模型请求超时") from exc
        except httpx.HTTPStatusError as exc:
            raise map_provider_http_error(exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise ProjectAnalysisProviderError("provider_connection_failed", "无法连接模型服务") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectAnalysisProviderError("invalid_model_response", "模型返回格式异常") from exc


class RuleBasedAssessmentProvider:
    """Deterministic local evaluator used until a model Provider is added."""

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
