import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from pipeline.collectors.urls import expand_url_variants

_SCHEMA_READY = False


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://devpulse:devpulse@localhost:5434/devpulse")


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    migration = Path(__file__).resolve().parents[2] / "infra" / "postgres" / "02-bundles.sql"
    if not migration.exists():
        _SCHEMA_READY = True
        return

    sql = migration.read_text(encoding="utf-8")
    with psycopg.connect(get_database_url()) as conn:
        conn.execute(sql)
        conn.commit()
    _SCHEMA_READY = True


@contextmanager
def get_conn():
    ensure_schema()
    with psycopg.connect(get_database_url(), row_factory=dict_row) as conn:
        yield conn


def upsert_post(conn, post: dict[str, Any]) -> tuple[str, str]:
    cur = conn.execute(
        """
        INSERT INTO posts (
            id, source, feed_type, title, url, summary, raw_content,
            author, published_at, upvotes, comments_count, status
        ) VALUES (
            %(id)s, %(source)s, %(feed_type)s, %(title)s, %(url)s,
            %(summary)s, %(raw_content)s, %(author)s, %(published_at)s,
            %(upvotes)s, %(comments_count)s, 'collected'
        )
        ON CONFLICT (url) DO UPDATE SET
            title = EXCLUDED.title,
            summary = EXCLUDED.summary,
            raw_content = EXCLUDED.raw_content,
            updated_at = NOW()
        RETURNING id, status
        """,
        post,
    )
    row = cur.fetchone()
    return row["id"], row["status"]


def fetch_posts_by_status(conn, status: str, limit: int = 10) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT * FROM posts
        WHERE status = %s
        ORDER BY published_at DESC NULLS LAST
        LIMIT %s
        """,
        (status, limit),
    )
    return cur.fetchall()


def fetch_posts_for_processing(conn, limit: int = 10) -> list[dict[str, Any]]:
    """collected 우선, summarized(중단 복구) 포함."""
    cur = conn.execute(
        """
        SELECT * FROM posts
        WHERE status IN ('collected', 'summarized')
        ORDER BY
            CASE status WHEN 'collected' THEN 0 ELSE 1 END,
            published_at DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )
    return cur.fetchall()


def clear_solo_video_keys(conn) -> int:
    """개별 영상(video_key만 있고 bundle_id 없음) 메타 정리."""
    cur = conn.execute(
        """
        UPDATE posts
        SET video_key = NULL, updated_at = NOW()
        WHERE video_key IS NOT NULL AND bundle_id IS NULL
        """
    )
    return cur.rowcount


def fetch_url_index(conn) -> tuple[set[str], set[str]]:
    """(모든 URL, 전체 본문 보유 URL) — canonical URL 변형 포함."""
    cur = conn.execute(
        """
        SELECT url, raw_content, summary
        FROM posts
        """
    )
    known: set[str] = set()
    full: set[str] = set()
    for row in cur.fetchall():
        url = row["url"]
        known.add(url)
        raw = row["raw_content"] or ""
        summary = row["summary"] or ""
        text = raw if len(raw) > len(summary) else summary
        if len(text) >= 800 and "..." not in text[-40:]:
            full.add(url)
    return expand_url_variants(known), expand_url_variants(full)


def count_posts_by_status(conn) -> dict[str, int]:
    cur = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM posts
        GROUP BY status
        """
    )
    return {row["status"]: row["count"] for row in cur.fetchall()}


def update_post_status(
    conn,
    post_id: str,
    status: str,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    fields = ["status = %s", "updated_at = NOW()"]
    values: list[Any] = [status]

    if extra:
        for key, value in extra.items():
            fields.append(f"{key} = %s")
            if isinstance(value, dict):
                values.append(Json(value))
            else:
                values.append(value)

    values.append(post_id)
    conn.execute(
        f"UPDATE posts SET {', '.join(fields)} WHERE id = %s",
        values,
    )
