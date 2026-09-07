"""Add per-question practice feedback.

Revision ID: 0007_question_feedbacks
Revises: 0006_question_template
"""

from alembic import op
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    inspect,
)


revision = "0007_question_feedbacks"
down_revision = "0006_question_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("question_feedbacks"):
        op.create_table(
            "question_feedbacks",
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
            Column("content", Text, nullable=False, server_default=""),
            Column("focus_hints_json", Text, nullable=False, server_default="[]"),
            Column("created_at", DateTime(timezone=True), nullable=True),
            UniqueConstraint("question_id", name="uq_question_feedback"),
        )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table("question_feedbacks"):
        op.drop_table("question_feedbacks")
