"""Attach contextual interview plan-node metadata to assessment runs.

Revision ID: 0019_graph_plan_node_scoring
Revises: 0018_interview_graph_events
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_graph_plan_node_scoring"
down_revision = "0018_interview_graph_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("assessment_runs")}
    if "plan_node_id" not in columns:
        op.add_column("assessment_runs", sa.Column("plan_node_id", sa.String(128), nullable=True))
        op.create_index("ix_assessment_runs_plan_node_id", "assessment_runs", ["plan_node_id"])


def downgrade() -> None:
    op.drop_index("ix_assessment_runs_plan_node_id", table_name="assessment_runs")
    op.drop_column("assessment_runs", "plan_node_id")
