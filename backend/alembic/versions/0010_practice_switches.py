"""Add followup/feedback switches and interviewer persona.

Revision ID: 0010_practice_switches
Revises: 0008_practice_sessions
"""

from alembic import op
from sqlalchemy import Boolean, Column, String, inspect


revision = "0010_practice_switches"
down_revision = "0008_practice_sessions"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _columns("model_settings")
    if not columns:
        return
    if "followup_enabled" not in columns:
        op.add_column(
            "model_settings",
            Column("followup_enabled", Boolean, nullable=False, server_default="1"),
        )
    if "practice_feedback_enabled" not in columns:
        op.add_column(
            "model_settings",
            Column(
                "practice_feedback_enabled", Boolean, nullable=False, server_default="1"
            ),
        )
    if "persona" not in columns:
        op.add_column(
            "model_settings",
            Column("persona", String(20), nullable=False, server_default="standard"),
        )


def downgrade() -> None:
    columns = _columns("model_settings")
    for name in ("persona", "practice_feedback_enabled", "followup_enabled"):
        if name in columns:
            op.drop_column("model_settings", name)
