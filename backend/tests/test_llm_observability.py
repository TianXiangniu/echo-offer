from decimal import Decimal

from sqlalchemy import select

from app.database import create_database
from app.llm_observability import ModelCallRecord, ModelPrice, calculate_cost_cny, record_model_calls
from app.models import LlmCallTrace


def test_calculate_cost_cny_requires_usage_and_both_prices():
    price = ModelPrice("model-a", Decimal("2.5"), Decimal("10"))

    assert calculate_cost_cny(1_000_000, 500_000, price) == Decimal("7.5")
    assert calculate_cost_cny(None, 500_000, price) is None
    assert calculate_cost_cny(1_000, 1_000, None) is None


def test_record_model_calls_persists_only_safe_metadata(tmp_path):
    _, session_factory = create_database(f"sqlite:///{tmp_path / 'traces.db'}")
    record = ModelCallRecord.success(
        trace_id="trace-1",
        call_kind="project_analysis",
        provider="siliconflow",
        model_name="model-a",
        prompt_version="analysis-v3",
        input_tokens=12,
        output_tokens=8,
        latency_ms=34,
        request_bytes=99,
        response_bytes=88,
    )

    with session_factory() as db:
        assert record_model_calls(db, [record], pricing=(), session_id=None, operation_job_id=None) == 1
        db.commit()
        saved = db.scalar(select(LlmCallTrace))

    assert saved.cost_cny is None
    assert "prompt" not in saved.__dict__
    assert "secret" not in repr(saved).lower()
