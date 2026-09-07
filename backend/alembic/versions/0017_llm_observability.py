"""Add local model pricing and LLM call traces.

Revision ID: 0017_llm_observability
Revises: 0016_converge_question_slugs
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_llm_observability"
down_revision = "0016_converge_question_slugs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    model_columns = {column["name"] for column in inspector.get_columns("model_settings")}
    if "pricing_json" not in model_columns:
        op.add_column("model_settings", sa.Column("pricing_json", sa.Text(), nullable=False, server_default="[]"))
    if inspector.has_table("llm_call_traces"):
        return
    op.create_table(
        "llm_call_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("interview_sessions.id")),
        sa.Column("operation_job_id", sa.String(36), sa.ForeignKey("operation_jobs.id")),
        sa.Column("call_kind", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("prompt_version", sa.String(80)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("input_tokens", sa.Integer()), sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("input_price_per_million_cny", sa.Numeric(18, 8)),
        sa.Column("output_price_per_million_cny", sa.Numeric(18, 8)),
        sa.Column("cost_cny", sa.Numeric(18, 8)), sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("request_bytes", sa.Integer()), sa.Column("response_bytes", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("trace_id", "session_id", "operation_job_id", "call_kind", "model_name", "status", "finished_at"):
        op.create_index(f"ix_llm_call_traces_{column}", "llm_call_traces", [column])


def downgrade() -> None:
    op.drop_table("llm_call_traces")
    op.drop_column("model_settings", "pricing_json")
