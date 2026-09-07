"""Add skill wiki pages and study log.

Revision ID: 0012_skill_wikis
Revises: 0011_run_commentary
"""

from alembic import op
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    inspect,
)


revision = "0012_skill_wikis"
down_revision = "0011_run_commentary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("skill_wikis"):
        op.create_table(
            "skill_wikis",
            Column("skill_id", String(80), ForeignKey("skill_catalog.id"), primary_key=True),
            Column("content_json", Text, nullable=False, server_default="{}"),
            Column("has_deep_dive", Boolean, nullable=False, server_default="0"),
            Column("source", String(20), nullable=False, server_default="preset"),
            Column("model_name", String(120), nullable=True),
            Column("prompt_version", String(80), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=True),
            Column("updated_at", DateTime(timezone=True), nullable=True),
        )
    if not inspector.has_table("skill_study_logs"):
        op.create_table(
            "skill_study_logs",
            Column("id", String(36), primary_key=True),
            Column("user_id", String(64), ForeignKey("users.id"), nullable=False, index=True),
            Column("skill_id", String(80), ForeignKey("skill_catalog.id"), nullable=False, index=True),
            Column("source", String(30), nullable=False, server_default="manual"),
            Column("studied_at", DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if inspector.has_table("skill_study_logs"):
        op.drop_table("skill_study_logs")
    if inspector.has_table("skill_wikis"):
        op.drop_table("skill_wikis")
