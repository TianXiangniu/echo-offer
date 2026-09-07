"""Add idempotent receipts for contextual interview graph events.

Revision ID: 0018_interview_graph_events
Revises: 0017_llm_observability
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_interview_graph_events"
down_revision = "0017_llm_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("interview_graph_event_receipts"):
        return
    op.create_table(
        "interview_graph_event_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("interview_sessions.id"),
            nullable=False,
        ),
        sa.Column("graph_step_id", sa.String(160), nullable=False),
        sa.Column("event_kind", sa.String(60), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "session_id",
            "graph_step_id",
            "event_kind",
            name="uq_graph_event_session_step_kind",
        ),
    )
    op.create_index(
        "ix_interview_graph_event_receipts_session_id",
        "interview_graph_event_receipts",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_table("interview_graph_event_receipts")
