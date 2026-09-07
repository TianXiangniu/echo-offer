"""Add interview followups and session followup budget.

Revision ID: 0005_interview_followups
Revises: 0004_model_settings
"""

from alembic import op
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)


revision = "0005_interview_followups"
down_revision = "0004_model_settings"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("interview_followups"):
        op.create_table(
            "interview_followups",
            Column("id", String(36), primary_key=True),
            Column(
                "session_id",
                String(36),
                ForeignKey("interview_sessions.id"),
                nullable=False,
                index=True,
            ),
            Column(
                "question_id",
                String(36),
                ForeignKey("interview_questions.id"),
                nullable=False,
                index=True,
            ),
            Column("round", Integer, nullable=False, server_default="1"),
            Column("question_text", Text, nullable=False, server_default=""),
            Column("decision_reason", String(30), nullable=False, server_default="probe"),
            Column("client_submission_id", String(120), nullable=True),
            Column("payload_hash", String(64), nullable=True),
            Column("answer_text", Text, nullable=True),
            Column("answer_text_hash", String(64), nullable=True),
            Column("status", String(20), nullable=False, server_default="pending"),
            Column("created_at", DateTime(timezone=True), nullable=True),
            Column("answered_at", DateTime(timezone=True), nullable=True),
            UniqueConstraint("question_id", "round", name="uq_followup_question_round"),
        )

    session_columns = _existing_columns("interview_sessions")
    if session_columns and "followup_budget_used" not in session_columns:
        op.add_column(
            "interview_sessions",
            Column("followup_budget_used", Integer, nullable=False, server_default="0"),
        )


def downgrade() -> None:
    session_columns = _existing_columns("interview_sessions")
    if session_columns and "followup_budget_used" in session_columns:
        op.drop_column("interview_sessions", "followup_budget_used")
    if inspect(op.get_bind()).has_table("interview_followups"):
        op.drop_table("interview_followups")
