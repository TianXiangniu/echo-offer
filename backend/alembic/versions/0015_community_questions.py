"""Add community question bank mined from interview experience notes.

Revision ID: 0015_community_questions
Revises: 0014_target_date
"""

from alembic import op
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)


revision = "0015_community_questions"
down_revision = "0014_target_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("community_questions"):
        op.create_table(
            "community_questions",
            Column("id", String(36), primary_key=True),
            Column("text", Text, nullable=False),
            Column("phase", String(20), nullable=False, index=True),
            Column("knowledge_point_slug", String(120), nullable=False, index=True),
            Column("note_url", Text, nullable=False, server_default=""),
            Column("note_id", String(80), nullable=False, index=True),
            Column("dup_count", Integer, nullable=False, server_default="1"),
            Column("content_hash", String(64), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=True),
            UniqueConstraint("content_hash", name="uq_community_question_content"),
        )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table("community_questions"):
        op.drop_table("community_questions")
