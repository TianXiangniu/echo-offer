"""Store per-question scorer commentary for personalized report reasons.

Revision ID: 0011_run_commentary
Revises: 0010_practice_switches
"""

from alembic import op
from sqlalchemy import Column, Text, inspect


revision = "0011_run_commentary"
down_revision = "0010_practice_switches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("assessment_runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("assessment_runs")}
    if "commentary" not in columns:
        op.add_column(
            "assessment_runs",
            Column("commentary", Text, nullable=True, server_default=None),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("assessment_runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("assessment_runs")}
    if "commentary" in columns:
        op.drop_column("assessment_runs", "commentary")
