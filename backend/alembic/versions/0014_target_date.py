"""Add target interview date for countdown training plan.

Revision ID: 0014_target_date
Revises: 0013_dialog_interview
"""

from alembic import op
from sqlalchemy import Column, DateTime, inspect


revision = "0014_target_date"
down_revision = "0013_dialog_interview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("interview_targets"):
        return
    columns = {column["name"] for column in inspector.get_columns("interview_targets")}
    if "target_date" not in columns:
        op.add_column(
            "interview_targets",
            Column("target_date", DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("interview_targets"):
        return
    columns = {column["name"] for column in inspector.get_columns("interview_targets")}
    if "target_date" in columns:
        op.drop_column("interview_targets", "target_date")
