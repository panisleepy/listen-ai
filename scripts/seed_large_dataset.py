#!/usr/bin/env python3
"""Duplicate existing posts rows until the database reaches a target row count.

Useful for benchmarking ListenAI at ~1M posts. Optionally pre-fill sentiment columns so
gateway can skip bulk NLP calls when measuring cache behaviour.

Examples:
  python scripts/seed_large_dataset.py --db ./data/listenai.db --target 1000000 --batch-size 8000 --fill-sentiment

Warning: Large SQLite files consume disk space and time. Run on free space disks only.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed SQLite posts table up to target count.")
    parser.add_argument(
        "--db",
        default="./data/listenai.db",
        help="Path to SQLite DB (relative to repo root unless absolute)",
    )
    parser.add_argument("--target", type=int, default=1_000_000, help="Desired minimum row count.")
    parser.add_argument("--batch-size", type=int, default=8000, help="Rows per INSERT batch.")
    parser.add_argument(
        "--fill-sentiment",
        action="store_true",
        help="Populate sentiment_* columns so gateway skips NLP on synthetic rows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts only; do not insert.",
    )
    return parser.parse_args()


def migrate_sentiment_columns(conn: sqlite3.Connection) -> None:
    stmts = [
        "ALTER TABLE posts ADD COLUMN sentiment_label TEXT",
        "ALTER TABLE posts ADD COLUMN sentiment_score INTEGER",
        "ALTER TABLE posts ADD COLUMN sentiment_version TEXT",
    ]
    for stmt in stmts:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


def ensure_schema(conn: sqlite3.Connection, fill_sentiment: bool) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    migrate_sentiment_columns(conn)
    conn.commit()


def fetch_templates(conn: sqlite3.Connection, limit: int = 5000):
    rows = conn.execute(
        """
        SELECT platform, author, content, created_at
        FROM posts
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        raise RuntimeError("posts table has no templates to duplicate")
    return rows


def seed(
    conn: sqlite3.Connection,
    templates,
    *,
    target: int,
    batch_size: int,
    fill_sentiment: bool,
) -> None:
    current = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    if current >= target:
        print({"status": "noop", "current_posts": current, "target": target})
        return

    seq = current
    version = "synthetic-seed-v1"
    label = "neutral"
    score = 33

    while current < target:
        chunk_limit = min(batch_size, target - current)
        batch = []
        for _ in range(chunk_limit):
            plat, auth, content, ts = templates[seq % len(templates)]
            seq += 1
            suffix = f"[dup#{seq}]"
            new_content = content + suffix
            if fill_sentiment:
                batch.append((plat, auth, new_content, ts, label, score, version))
            else:
                batch.append((plat, auth, new_content, ts))

        if fill_sentiment:
            conn.executemany(
                """
                INSERT INTO posts(platform, author, content, created_at,
                                  sentiment_label, sentiment_score, sentiment_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
        else:
            conn.executemany(
                """
                INSERT INTO posts(platform, author, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                batch,
            )
        conn.commit()
        current = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        print({"inserted_batch": len(batch), "current_posts": current})


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = (root / db_path).resolve()

    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn, args.fill_sentiment)
        current = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        if args.dry_run:
            print({"db": str(db_path), "current_posts": current, "target": args.target})
            return 0
        templates = fetch_templates(conn)
        start = time.perf_counter()
        seed(
            conn,
            templates,
            target=args.target,
            batch_size=args.batch_size,
            fill_sentiment=args.fill_sentiment,
        )
        elapsed = time.perf_counter() - start
        final = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        print({"db": str(db_path), "final_posts": final, "elapsed_sec": round(elapsed, 2)})
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
