"""Allow foundation interview sessions without a resume project."""

from alembic import op
import sqlalchemy as sa


revision = "0021_foundation_sessions"
down_revision = "0020_graph_submission_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("interview_sessions") as batch:
        batch.alter_column(
            "resume_project_id",
            existing_type=sa.String(36),
            nullable=True,
        )


def downgrade() -> None:
    null_count = op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM interview_sessions "
            "WHERE resume_project_id IS NULL"
        )
    )
    if null_count:
        raise RuntimeError("cannot downgrade while foundation sessions exist")
    with op.batch_alter_table("interview_sessions") as batch:
        batch.alter_column(
            "resume_project_id",
            existing_type=sa.String(36),
            nullable=False,
        )
