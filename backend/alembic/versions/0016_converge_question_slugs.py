"""Converge community question new: slugs onto skill_catalog ids, add index.

Revision ID: 0016_converge_question_slugs
Revises: 0015_community_questions
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from alembic import op
from sqlalchemy import inspect, text

from app.slug_map import SLUG_MAP

revision = "0016_converge_question_slugs"
down_revision = "0015_community_questions"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _columns("community_questions")
    if not columns:
        return

    bind = op.get_bind()
    if "knowledge_point_slug" in columns and not inspect(bind).get_indexes("community_questions"):
        op.create_index(
            "ix_community_questions_kp_slug",
            "community_questions",
            ["knowledge_point_slug"],
        )

    if "knowledge_point_slug" not in columns:
        return

    rows = bind.execute(
        text("SELECT id, knowledge_point_slug FROM community_questions")
    ).all()
    backup_path = Path(__file__).resolve().parents[2] / "data" / "slug_backup_0016.json"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "rows": {row_id: slug for row_id, slug in rows},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for old_slug, new_slug in SLUG_MAP.items():
        bind.execute(
            text(
                "UPDATE community_questions SET knowledge_point_slug = :new_slug "
                "WHERE knowledge_point_slug = :old_slug"
            ),
            {"new_slug": new_slug, "old_slug": old_slug},
        )


def downgrade() -> None:
    columns = _columns("community_questions")
    if "knowledge_point_slug" not in columns:
        return
    backup_path = Path(__file__).resolve().parents[2] / "data" / "slug_backup_0016.json"
    if not backup_path.exists():
        return
    rows = json.loads(backup_path.read_text(encoding="utf-8"))["rows"]
    bind = op.get_bind()
    for row_id, slug in rows.items():
        bind.execute(
            text(
                "UPDATE community_questions SET knowledge_point_slug = :slug "
                "WHERE id = :row_id"
            ),
            {"slug": slug, "row_id": row_id},
        )
