"""Add local model settings.

Revision ID: 0004_model_settings
Revises: 0003_profile_skill_state_scope
"""

from alembic import op
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)


revision = "0004_model_settings"
down_revision = "0003_profile_skill_state_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("model_settings"):
        return
    op.create_table(
        "model_settings",
        Column("id", String(36), primary_key=True),
        Column("user_id", String(64), ForeignKey("users.id"), nullable=False),
        Column("base_url", String(255), nullable=False),
        Column("model", String(160), nullable=False),
        Column("assessment_model", String(160), nullable=False),
        Column("temperature", Float, nullable=False),
        Column("max_tokens", Integer, nullable=False),
        Column("timeout_seconds", Float, nullable=False),
        Column("assessment_batch_size", Integer, nullable=False),
        Column("api_key", Text, nullable=False, server_default=""),
        Column("updated_at", DateTime(timezone=True), nullable=True),
        UniqueConstraint("user_id", name="uq_model_settings_user"),
    )


def downgrade() -> None:
    op.drop_table("model_settings")
