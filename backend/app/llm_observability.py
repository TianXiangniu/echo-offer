from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from threading import Lock
from uuid import uuid4

from sqlalchemy.orm import Session

from .models import LlmCallTrace, utc_now


@dataclass(frozen=True, slots=True)
class ModelPrice:
    model_name: str
    input_price_per_million_cny: Decimal
    output_price_per_million_cny: Decimal


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    trace_id: str
    call_kind: str
    provider: str
    model_name: str
    prompt_version: str | None
    status: str
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    request_bytes: int | None
    response_bytes: int | None
    created_at: datetime
    finished_at: datetime

    @classmethod
    def success(cls, *, trace_id: str, call_kind: str, provider: str, model_name: str,
                prompt_version: str | None, input_tokens: int | None,
                output_tokens: int | None, latency_ms: int, request_bytes: int | None,
                response_bytes: int | None) -> ModelCallRecord:
        now = utc_now()
        return cls(trace_id, call_kind, provider, model_name, prompt_version, "succeeded", None,
                   input_tokens, output_tokens, latency_ms, request_bytes, response_bytes, now, now)


@dataclass
class ModelCallCapture:
    trace_id: str
    records: list[ModelCallRecord]
    lock: Lock

    def add(self, record: ModelCallRecord) -> None:
        with self.lock:
            self.records.append(record)


_capture: ContextVar[ModelCallCapture | None] = ContextVar("llm_call_capture", default=None)


@contextmanager
def capture_model_calls(trace_id: str):
    capture = ModelCallCapture(trace_id, [], Lock())
    token = _capture.set(capture)
    try:
        yield capture
    finally:
        _capture.reset(token)


def emit_model_call(record: ModelCallRecord) -> None:
    capture = _capture.get()
    if capture is not None:
        capture.add(replace(record, trace_id=capture.trace_id))


def calculate_cost_cny(input_tokens: int | None, output_tokens: int | None,
                       price: ModelPrice | None) -> Decimal | None:
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return (
        Decimal(input_tokens) * price.input_price_per_million_cny
        + Decimal(output_tokens) * price.output_price_per_million_cny
    ) / Decimal(1_000_000)


def record_model_calls(db: Session, records: list[ModelCallRecord] | tuple[ModelCallRecord, ...], *,
                       pricing: tuple[ModelPrice, ...], session_id: str | None,
                       operation_job_id: str | None) -> int:
    prices = {price.model_name: price for price in pricing}
    for record in records:
        price = prices.get(record.model_name)
        cost = calculate_cost_cny(record.input_tokens, record.output_tokens, price)
        db.add(LlmCallTrace(
            id=str(uuid4()), trace_id=record.trace_id, session_id=session_id,
            operation_job_id=operation_job_id, call_kind=record.call_kind,
            provider=record.provider, model_name=record.model_name,
            prompt_version=record.prompt_version, status=record.status,
            error_code=record.error_code, input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            total_tokens=(record.input_tokens + record.output_tokens
                          if record.input_tokens is not None and record.output_tokens is not None else None),
            input_price_per_million_cny=(price.input_price_per_million_cny if price else None),
            output_price_per_million_cny=(price.output_price_per_million_cny if price else None),
            cost_cny=cost, latency_ms=record.latency_ms, request_bytes=record.request_bytes,
            response_bytes=record.response_bytes, created_at=record.created_at,
            finished_at=record.finished_at,
        ))
    db.flush()
    return len(records)
