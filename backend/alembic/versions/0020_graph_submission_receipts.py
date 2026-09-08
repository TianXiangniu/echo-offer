"""Reserve graph submissions before model execution."""

from alembic import op
import sqlalchemy as sa


revision = "0020_graph_submission_receipts"
down_revision = "0019_graph_plan_node_scoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "interview_graph_submission_receipts" in inspector.get_table_names():
        return
    op.create_table(
        "interview_graph_submission_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("interview_sessions.id"), nullable=False),
        sa.Column("client_submission_id", sa.String(120), nullable=False),
        sa.Column("answer_text_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "session_id",
            "client_submission_id",
            name="uq_graph_submission_session_client",
        ),
    )
    op.create_index(
        "ix_interview_graph_submission_receipts_session_id",
        "interview_graph_submission_receipts",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_graph_submission_receipts_session_id",
        table_name="interview_graph_submission_receipts",
    )
    op.drop_table("interview_graph_submission_receipts")
