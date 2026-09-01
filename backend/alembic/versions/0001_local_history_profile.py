"""Create local history and profile schema.

Revision ID: 0001_local_history_profile
Revises:
"""
from alembic import op
from sqlalchemy import Column, DateTime, String, inspect

from app.models import Base


revision = "0001_local_history_profile"
down_revision = None
branch_labels = None
depends_on = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    # create_all supplies all new tables and is a no-op for tables already present.
    # The explicit column checks below upgrade the pre-migration app.db safely.
    Base.metadata.create_all(bind=bind)

    for name, column in (
        ("profile_id", Column("profile_id", String(36), nullable=True)),
        ("current_assessment_run_id", Column("current_assessment_run_id", String(36), nullable=True)),
        ("current_report_id", Column("current_report_id", String(36), nullable=True)),
        ("archived_at", Column("archived_at", DateTime(timezone=True), nullable=True)),
    ):
        if not _has_column(bind, "interview_sessions", name):
            op.add_column("interview_sessions", column)


def downgrade() -> None:
    # The local application does not downgrade data-bearing history columns.
    pass
