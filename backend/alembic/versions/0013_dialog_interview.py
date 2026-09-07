"""Add dialog interview: project dialog turns and session stage.

Revision ID: 0013_dialog_interview
Revises: 0012_skill_wikis
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


revision = "0013_dialog_interview"
down_revision = "0012_skill_wikis"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("project_dialogs"):
        op.create_table(
            "project_dialogs",
            Column("id", String(36), primary_key=True),
            Column(
                "session_id",
                String(36),
                ForeignKey("interview_sessions.id"),
                nullable=False,
                index=True,
            ),
            Column("turn_no", Integer, nullable=False),
            Column("role", String(20), nullable=False),
            Column("content", Text, nullable=False),
            Column("kind", String(30), nullable=False, server_default="dialog"),
            Column("heuristic_tag", String(30), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=True),
            UniqueConstraint("session_id", "turn_no", "role", name="uq_dialog_turn_role"),
        )

    session_columns = _columns("interview_sessions")
    if session_columns:
        if "stage" not in session_columns:
            op.add_column(
                "interview_sessions",
                Column("stage", String(20), nullable=False, server_default="knowledge"),
            )
        if "dialog_rounds" not in session_columns:
            op.add_column(
                "interview_sessions",
                Column("dialog_rounds", Integer, nullable=True),
            )
        if "mode" not in session_columns:
            op.add_column(
                "interview_sessions",
                Column("mode", String(20), nullable=False, server_default="classic"),
            )


def downgrade() -> None:
    session_columns = _columns("interview_sessions")
    if session_columns:
        for name in ("mode", "dialog_rounds", "stage"):
            if name in session_columns:
                op.drop_column("interview_sessions", name)
    if inspect(op.get_bind()).has_table("project_dialogs"):
        op.drop_table("project_dialogs")
