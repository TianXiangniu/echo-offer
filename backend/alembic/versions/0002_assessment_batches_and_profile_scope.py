"""Add explicit assessment batches and profile-scoped knowledge states.

Revision ID: 0002_assessment_batches_and_profile_scope
Revises: 0001_local_history_profile
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
    text,
)


revision = "0002_assessment_batches_and_profile_scope"
down_revision = "0001_local_history_profile"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return inspect(bind).has_table(name)


def _has_column(bind, table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in inspect(bind).get_columns(table_name)
    }


def _has_index(bind, table_name: str, index_name: str) -> bool:
    return index_name in {
        index["name"] for index in inspect(bind).get_indexes(table_name)
    }


def _add_column_if_missing(table_name: str, column: Column) -> None:
    bind = op.get_bind()
    if _has_table(bind, table_name) and not _has_column(bind, table_name, column.name):
        op.add_column(table_name, column)


def _add_index_if_missing(table_name: str, index_name: str, column_name: str) -> None:
    bind = op.get_bind()
    if _has_table(bind, table_name) and not _has_index(bind, table_name, index_name):
        op.create_index(index_name, table_name, [column_name])


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "assessment_batches"):
        op.create_table(
            "assessment_batches",
            Column("id", String(36), primary_key=True),
            Column(
                "session_id",
                String(36),
                ForeignKey("interview_sessions.id"),
                nullable=False,
            ),
            Column("operation_job_id", String(36), nullable=True),
            Column("attempt_number", Integer, nullable=False, server_default="1"),
            Column("evaluator", String(80), nullable=False),
            Column("status", String(30), nullable=False, server_default="pending"),
            Column("error_code", String(80), nullable=True),
            Column("error_message", Text, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=True),
            Column("finished_at", DateTime(timezone=True), nullable=True),
            UniqueConstraint(
                "session_id",
                "attempt_number",
                name="uq_assessment_batch_attempt",
            ),
        )

    _add_column_if_missing(
        "interview_sessions",
        Column("current_assessment_batch_id", String(36), nullable=True),
    )
    _add_column_if_missing(
        "assessment_runs",
        Column("assessment_batch_id", String(36), nullable=True),
    )
    _add_column_if_missing(
        "operation_jobs",
        Column("assessment_batch_id", String(36), nullable=True),
    )
    _add_column_if_missing(
        "interview_reports",
        Column("assessment_batch_id", String(36), nullable=True),
    )
    _add_column_if_missing(
        "candidate_knowledge_states",
        Column("profile_id", String(36), nullable=True),
    )

    # Existing local data predates profile-scoped states. Attach it to the
    # user's first profile so it remains visible, while new writes require an
    # explicit profile in the application layer.
    if _has_table(bind, "candidate_knowledge_states") and _has_column(
        bind, "candidate_knowledge_states", "profile_id"
    ):
        op.execute(
            text(
                """
                UPDATE candidate_knowledge_states
                SET profile_id = (
                    SELECT candidate_profiles.id
                    FROM candidate_profiles
                    WHERE candidate_profiles.user_id = candidate_knowledge_states.user_id
                    ORDER BY candidate_profiles.created_at, candidate_profiles.id
                    LIMIT 1
                )
                WHERE profile_id IS NULL
                """
            )
        )

    _add_index_if_missing(
        "interview_sessions", "ix_interview_sessions_profile_id", "profile_id"
    )
    _add_index_if_missing(
        "assessment_runs", "ix_assessment_runs_assessment_batch_id", "assessment_batch_id"
    )
    _add_index_if_missing(
        "operation_jobs", "ix_operation_jobs_assessment_batch_id", "assessment_batch_id"
    )
    _add_index_if_missing(
        "interview_reports", "ix_interview_reports_assessment_batch_id", "assessment_batch_id"
    )
    _add_index_if_missing(
        "candidate_knowledge_states",
        "ix_candidate_knowledge_states_profile_id",
        "profile_id",
    )
    _add_index_if_missing(
        "assessment_batches", "ix_assessment_batches_session_id", "session_id"
    )
    _add_index_if_missing(
        "assessment_batches", "ix_assessment_batches_operation_job_id", "operation_job_id"
    )


def downgrade() -> None:
    # This is a data-bearing local history migration. Keep the columns and
    # batch records on downgrade rather than risking silent loss of history.
    pass
