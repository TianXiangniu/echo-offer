"""Persistence and redacted serialization for local model settings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
import json
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    ANALYSIS_TIMEOUT_SECONDS,
    ASSESSMENT_CASE_BATCH_SIZE,
    ASSESSMENT_TIMEOUT_SECONDS,
    LOCAL_USER_ID,
    MODEL_MAX_TOKENS,
    MODEL_TEMPERATURE,
    SILICONFLOW_ASSESSMENT_MODEL,
    SILICONFLOW_API_KEY,
    SILICONFLOW_BASE_URL,
    SILICONFLOW_MODEL,
)
from .models import ModelSetting, User, utc_now
from .schemas import ModelSettingsUpdate
from .llm_observability import ModelPrice


class ModelSettingsError(ValueError):
    code = "invalid_settings"


@dataclass(frozen=True, slots=True)
class ModelSettingsValues:
    base_url: str
    model: str
    assessment_model: str
    api_key: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    assessment_batch_size: int
    followup_enabled: bool = True
    practice_feedback_enabled: bool = True
    persona: str = "standard"
    pricing: tuple[ModelPrice, ...] = ()
    updated_at: datetime | None = None


def default_model_settings() -> ModelSettingsValues:
    return ModelSettingsValues(
        base_url=SILICONFLOW_BASE_URL,
        model=SILICONFLOW_MODEL,
        assessment_model=SILICONFLOW_ASSESSMENT_MODEL,
        api_key=SILICONFLOW_API_KEY,
        temperature=MODEL_TEMPERATURE,
        max_tokens=MODEL_MAX_TOKENS,
        timeout_seconds=max(ANALYSIS_TIMEOUT_SECONDS, ASSESSMENT_TIMEOUT_SECONDS),
        assessment_batch_size=ASSESSMENT_CASE_BATCH_SIZE,
        followup_enabled=True,
        practice_feedback_enabled=True,
        persona="standard",
        pricing=(),
    )


def _normalize_model_settings(settings: ModelSettingsValues) -> ModelSettingsValues:
    parsed_url = urlparse(settings.base_url.strip())
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ModelSettingsError("base_url 必须是完整的 HTTP 或 HTTPS 地址")
    if not settings.model.strip():
        raise ModelSettingsError("model 不能为空")
    if not settings.assessment_model.strip():
        raise ModelSettingsError("assessment_model 不能为空")
    return ModelSettingsValues(
        base_url=parsed_url.geturl().rstrip("/"),
        model=settings.model.strip(),
        assessment_model=settings.assessment_model.strip(),
        api_key=settings.api_key,
        temperature=float(settings.temperature),
        max_tokens=int(settings.max_tokens),
        timeout_seconds=float(settings.timeout_seconds),
        assessment_batch_size=int(settings.assessment_batch_size),
        followup_enabled=bool(settings.followup_enabled),
        practice_feedback_enabled=bool(settings.practice_feedback_enabled),
        persona=settings.persona,
        pricing=tuple(sorted(settings.pricing, key=lambda item: item.model_name)),
        updated_at=settings.updated_at,
    )


def validate_model_settings(settings: ModelSettingsValues) -> ModelSettingsValues:
    # 请求体已由 ModelSettingsUpdate 的 Pydantic 约束校验；这里防的是
    # 直接读库（load_model_settings）时可能被手改过的历史数据。
    if not 0 <= settings.temperature <= 2:
        raise ModelSettingsError("temperature 必须在 0 到 2 之间")
    if not 256 <= settings.max_tokens <= 8192:
        raise ModelSettingsError("max_tokens 必须在 256 到 8192 之间")
    if not 10 <= settings.timeout_seconds <= 300:
        raise ModelSettingsError("timeout_seconds 必须在 10 到 300 之间")
    if not 1 <= settings.assessment_batch_size <= 5:
        raise ModelSettingsError("assessment_batch_size 必须在 1 到 5 之间")
    if settings.persona not in {"gentle", "standard", "pressure"}:
        raise ModelSettingsError("persona 必须是 gentle、standard 或 pressure")
    return _normalize_model_settings(settings)


def _pricing_from_json(raw: str) -> tuple[ModelPrice, ...]:
    try:
        values = json.loads(raw or "[]")
        prices = tuple(ModelPrice(
            str(item["model_name"]).strip(), Decimal(str(item["input_price_per_million_cny"])),
            Decimal(str(item["output_price_per_million_cny"])),
        ) for item in values)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ModelSettingsError("pricing 配置格式错误") from exc
    names = [price.model_name for price in prices]
    if not all(names) or len(names) != len(set(names)) or any(
        not price.input_price_per_million_cny.is_finite() or not price.output_price_per_million_cny.is_finite()
        or price.input_price_per_million_cny < 0 or price.output_price_per_million_cny < 0 for price in prices
    ):
        raise ModelSettingsError("pricing 必须是模型名唯一的非负金额")
    return tuple(sorted(prices, key=lambda item: item.model_name))


def _pricing_to_json(pricing: tuple[ModelPrice, ...]) -> str:
    return json.dumps([{
        "model_name": item.model_name,
        "input_price_per_million_cny": str(item.input_price_per_million_cny),
        "output_price_per_million_cny": str(item.output_price_per_million_cny),
    } for item in pricing], ensure_ascii=False, sort_keys=True)


def load_model_settings(db: Session) -> ModelSettingsValues:
    row = db.scalar(
        select(ModelSetting).where(ModelSetting.user_id == LOCAL_USER_ID)
    )
    if row is None:
        return default_model_settings()
    return validate_model_settings(
        ModelSettingsValues(
            base_url=row.base_url,
            model=row.model,
            assessment_model=row.assessment_model,
            api_key=row.api_key,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
            timeout_seconds=row.timeout_seconds,
            assessment_batch_size=row.assessment_batch_size,
            followup_enabled=bool(row.followup_enabled),
            practice_feedback_enabled=bool(row.practice_feedback_enabled),
            persona=row.persona,
            pricing=_pricing_from_json(row.pricing_json),
            updated_at=row.updated_at,
        )
    )


def save_model_settings(
    db: Session,
    payload: ModelSettingsUpdate,
) -> ModelSettingsValues:
    current = load_model_settings(db)
    api_key = current.api_key
    if payload.clear_api_key:
        api_key = ""
    elif payload.api_key:
        api_key = payload.api_key
    values = _normalize_model_settings(
        ModelSettingsValues(
            base_url=payload.base_url,
            model=payload.model,
            assessment_model=payload.assessment_model,
            api_key=api_key,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            timeout_seconds=payload.timeout_seconds,
            assessment_batch_size=payload.assessment_batch_size,
            followup_enabled=payload.followup_enabled,
            practice_feedback_enabled=payload.practice_feedback_enabled,
            persona=payload.persona,
            pricing=_pricing_from_json(json.dumps([item.model_dump(mode="json") for item in payload.pricing])),
        )
    )
    user = db.get(User, LOCAL_USER_ID)
    if user is None:
        db.add(User(id=LOCAL_USER_ID))
        db.flush()
    row = db.scalar(
        select(ModelSetting).where(ModelSetting.user_id == LOCAL_USER_ID)
    )
    if row is None:
        row = ModelSetting(id=str(uuid4()), user_id=LOCAL_USER_ID)
        db.add(row)
    row.base_url = values.base_url
    row.model = values.model
    row.assessment_model = values.assessment_model
    row.api_key = values.api_key
    row.temperature = values.temperature
    row.max_tokens = values.max_tokens
    row.timeout_seconds = values.timeout_seconds
    row.assessment_batch_size = values.assessment_batch_size
    row.followup_enabled = values.followup_enabled
    row.practice_feedback_enabled = values.practice_feedback_enabled
    row.persona = values.persona
    row.pricing_json = _pricing_to_json(values.pricing)
    row.updated_at = utc_now()
    db.flush()
    return replace(values, updated_at=row.updated_at)


def public_model_settings(settings: ModelSettingsValues) -> dict:
    return {
        "base_url": settings.base_url,
        "model": settings.model,
        "assessment_model": settings.assessment_model,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "timeout_seconds": settings.timeout_seconds,
        "assessment_batch_size": settings.assessment_batch_size,
        "followup_enabled": settings.followup_enabled,
        "practice_feedback_enabled": settings.practice_feedback_enabled,
        "persona": settings.persona,
        "pricing": [{
            "model_name": item.model_name,
            "input_price_per_million_cny": str(item.input_price_per_million_cny),
            "output_price_per_million_cny": str(item.output_price_per_million_cny),
        } for item in settings.pricing],
        "api_key_configured": bool(settings.api_key),
        "updated_at": settings.updated_at,
    }
