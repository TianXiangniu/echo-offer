"""Support drill and verification practice sessions.

Revision ID: 0008_practice_sessions
Revises: 0007_question_feedbacks
"""

from alembic import op
from sqlalchemy import Column, DateTime, String, inspect


revision = "0008_practice_sessions"
down_revision = "0007_question_feedbacks"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    session_columns = _columns("interview_sessions")
    if session_columns:
        if "session_kind" not in session_columns:
            op.add_column(
                "interview_sessions",
                Column("session_kind", String(20), nullable=False, server_default="interview"),
            )
        if "source_recommendation_id" not in session_columns:
            # SQLite 不支持 ALTER 添加外键约束，关联语义由应用层维护
            op.add_column(
                "interview_sessions",
                Column("source_recommendation_id", String(36), nullable=True),
            )

    recommendation_columns = _columns("learning_recommendations")
    if recommendation_columns and "practice_completed_at" not in recommendation_columns:
        op.add_column(
            "learning_recommendations",
            Column("practice_completed_at", DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    recommendation_columns = _columns("learning_recommendations")
    if recommendation_columns and "practice_completed_at" in recommendation_columns:
        op.drop_column("learning_recommendations", "practice_completed_at")

    session_columns = _columns("interview_sessions")
    if session_columns:
        if "source_recommendation_id" in session_columns:
            op.drop_column("interview_sessions", "source_recommendation_id")
        if "session_kind" in session_columns:
            op.drop_column("interview_sessions", "session_kind")
