"""Track which question template each interview question came from.

Revision ID: 0006_question_template_id
Revises: 0005_interview_followups
"""

from alembic import op
from sqlalchemy import Column, String, inspect


revision = "0006_question_template"
down_revision = "0005_interview_followups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("interview_questions"):
        return
    columns = {column["name"] for column in inspector.get_columns("interview_questions")}
    if "template_id" not in columns:
        op.add_column(
            "interview_questions",
            Column("template_id", String(160), nullable=True, server_default=None),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("interview_questions"):
        return
    columns = {column["name"] for column in inspector.get_columns("interview_questions")}
    if "template_id" in columns:
        op.drop_column("interview_questions", "template_id")
