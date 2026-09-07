"""Import mined community questions (JSONL) into the community_questions table.

Usage:
    python scripts/import_community_questions.py <questions.jsonl> [more.jsonl ...]

Idempotent: rows are keyed by content_hash (sha1 of whitespace/punctuation-normalized
text); duplicates within or across input files collapse into one row whose dup_count
records how many raw occurrences were seen.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEFAULT_DATABASE_URL  # noqa: E402
from app.database import create_database  # noqa: E402
from app.models import CommunityQuestion  # noqa: E402
from app.slug_map import SLUG_MAP  # noqa: E402

PHASES = {"项目", "八股", "手撕", "HR"}
_NOISE = re.compile(r"[\s，。？?！!：:；;、\.·…\"“”‘’（）()\-—_`]")
_PREFIX = re.compile(r"^(手撕|算法题|算法|LeetCode|手写)[::]?")


def normalize(text: str) -> str:
    return _PREFIX.sub("", _NOISE.sub("", text))


def load_rows(paths: list[str]) -> dict[str, dict]:
    """Group raw rows by normalized text, keeping the most complete variant."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                phase = raw.get("phase", "")
                text = (raw.get("text") or "").strip()
                if phase not in PHASES or len(normalize(text)) < 4:
                    continue
                groups[normalize(text)].append(
                    {
                        "text": text,
                        "phase": phase,
                        "knowledge_point_slug": SLUG_MAP.get(
                            (raw.get("knowledge_point") or "").strip(),
                            (raw.get("knowledge_point") or "").strip(),
                        ),
                        "note_url": raw.get("note_url") or "",
                        "note_id": raw.get("note_id") or "",
                    }
                )
    merged: dict[str, dict] = {}
    for key, variants in groups.items():
        best = max(variants, key=lambda row: len(row["text"]))
        best["dup_count"] = len(variants)
        merged[key] = best
    return merged


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    rows = load_rows(sys.argv[1:])
    for row in rows.values():
        row["content_hash"] = hashlib.sha1(
            normalize(row["text"]).encode("utf-8")
        ).hexdigest()

    engine, factory = create_database(DEFAULT_DATABASE_URL)
    session = factory()
    try:
        existing = {
            hash_
            for (hash_,) in session.query(CommunityQuestion.content_hash).all()
        }
        inserted = skipped = 0
        for row in rows.values():
            if row["content_hash"] in existing:
                skipped += 1
                continue
            session.add(
                CommunityQuestion(
                    id=str(uuid.uuid4()),
                    text=row["text"],
                    phase=row["phase"],
                    knowledge_point_slug=row["knowledge_point_slug"],
                    note_url=row["note_url"],
                    note_id=row["note_id"],
                    dup_count=row["dup_count"],
                    content_hash=row["content_hash"],
                )
            )
            existing.add(row["content_hash"])
            inserted += 1
        session.commit()
        total = session.query(CommunityQuestion).count()
        print(f"导入 {inserted} 题，跳过已存在 {skipped} 题，表内共 {total} 题")
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
