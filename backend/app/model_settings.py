"""Persistence and redacted serialization for local model settings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
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
    )


def validate_model_settings(settings: ModelSettingsValues) -> ModelSettingsValues:
    parsed_url = urlparse(settings.base_url.strip())
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ModelSettingsError("base_url 必须是完整的 HTTP 或 HTTPS 地址")
    if not settings.model.strip():
        raise ModelSettingsError("model 不能为空")
    if not settings.assessment_model.strip():
        raise ModelSettingsError("assessment_model 不能为空")
    if not 0 <= settings.temperature <= 2:
        raise ModelSettingsError("temperature 必须在 0 到 2 之间")
    if not 256 <= settings.max_tokens <= 8192:
        raise ModelSettingsError("max_tokens 必须在 256 到 8192 之间")
    if not 10 <= settings.timeout_seconds <= 300:
        raise ModelSettingsError("timeout_seconds 必须在 10 到 300 之间")
    if not 1 <= settings.assessment_batch_size <= 5:
        raise ModelSettingsError("assessment_batch_size 必须在 1 到 5 之间")
    return ModelSettingsValues(
        base_url=parsed_url.geturl().rstrip("/"),
        model=settings.model.strip(),
        assessment_model=settings.assessment_model.strip(),
        api_key=settings.api_key,
        temperature=float(settings.temperature),
        max_tokens=int(settings.max_tokens),
        timeout_seconds=float(settings.timeout_seconds),
        assessment_batch_size=int(settings.assessment_batch_size),
        updated_at=settings.updated_at,
    )


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
    values = validate_model_settings(
        ModelSettingsValues(
            base_url=payload.base_url,
            model=payload.model,
            assessment_model=payload.assessment_model,
            api_key=api_key,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            timeout_seconds=payload.timeout_seconds,
            assessment_batch_size=payload.assessment_batch_size,
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
        "api_key_configured": bool(settings.api_key),
        "updated_at": settings.updated_at,
    }
