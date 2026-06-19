import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass
class PostRecord:
  bundle_id: str
  kind: str
  ig_media_id: str | None
  posted_at: str | None
  error: str | None
  content_key: str | None = None


@dataclass(frozen=True)
class ContentPost:
  bundle_id: str
  ig_media_id: str


class StateStore:
  def __init__(self, db_path: Path, timezone: str) -> None:
    self.db_path = db_path
    self.tz = ZoneInfo(timezone)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    self._init_db()

  @contextmanager
  def _conn(self):
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    try:
      yield conn
      conn.commit()
    finally:
      conn.close()

  def _init_db(self) -> None:
    with self._conn() as conn:
      conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ig_posts (
          bundle_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          ig_media_id TEXT,
          posted_at TEXT,
          error TEXT,
          content_key TEXT,
          PRIMARY KEY (bundle_id, kind)
        );
        CREATE TABLE IF NOT EXISTS ig_daily (
          day TEXT NOT NULL,
          kind TEXT NOT NULL,
          count INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (day, kind)
        );
        """
      )
      columns = {row[1] for row in conn.execute("PRAGMA table_info(ig_posts)")}
      if "content_key" not in columns:
        conn.execute("ALTER TABLE ig_posts ADD COLUMN content_key TEXT")
      conn.execute("CREATE INDEX IF NOT EXISTS idx_ig_posts_content_key ON ig_posts(content_key, kind)")

  def today(self) -> date:
    return datetime.now(self.tz).date()

  def count_today(self, kind: str) -> int:
    day = self.today().isoformat()
    with self._conn() as conn:
      row = conn.execute(
        "SELECT count FROM ig_daily WHERE day = ? AND kind = ?",
        (day, kind),
      ).fetchone()
    return int(row["count"]) if row else 0

  def increment_today(self, kind: str) -> None:
    day = self.today().isoformat()
    with self._conn() as conn:
      conn.execute(
        """
        INSERT INTO ig_daily (day, kind, count) VALUES (?, ?, 1)
        ON CONFLICT(day, kind) DO UPDATE SET count = count + 1
        """,
        (day, kind),
      )

  def is_posted(self, bundle_id: str, kind: str) -> bool:
    with self._conn() as conn:
      row = conn.execute(
        "SELECT ig_media_id FROM ig_posts WHERE bundle_id = ? AND kind = ? AND ig_media_id IS NOT NULL",
        (bundle_id, kind),
      ).fetchone()
    return row is not None

  def find_posted_content(self, content_key: str, kind: str) -> ContentPost | None:
    if not content_key:
      return None
    with self._conn() as conn:
      row = conn.execute(
        """
        SELECT bundle_id, ig_media_id
        FROM ig_posts
        WHERE content_key = ? AND kind = ? AND ig_media_id IS NOT NULL
        ORDER BY posted_at
        LIMIT 1
        """,
        (content_key, kind),
      ).fetchone()
    if not row:
      return None
    return ContentPost(bundle_id=row["bundle_id"], ig_media_id=row["ig_media_id"])

  def mark_posted(
    self,
    bundle_id: str,
    kind: str,
    ig_media_id: str,
    *,
    content_key: str | None = None,
  ) -> None:
    now = datetime.now(self.tz).isoformat()
    with self._conn() as conn:
      conn.execute(
        """
        INSERT INTO ig_posts (bundle_id, kind, ig_media_id, posted_at, error, content_key)
        VALUES (?, ?, ?, ?, NULL, ?)
        ON CONFLICT(bundle_id, kind) DO UPDATE SET
          ig_media_id = excluded.ig_media_id,
          posted_at = excluded.posted_at,
          error = NULL,
          content_key = COALESCE(excluded.content_key, ig_posts.content_key)
        """,
        (bundle_id, kind, ig_media_id, now, content_key),
      )

  def backfill_content_keys(self, jobs: list) -> int:
    """기존 게시 기록에 content_key를 채워 콘텐츠 중복 감지를 활성화."""
    by_id = {job.bundle_id: job.content_key for job in jobs}
    updated = 0
    with self._conn() as conn:
      rows = conn.execute(
        """
        SELECT bundle_id, kind FROM ig_posts
        WHERE ig_media_id IS NOT NULL AND (content_key IS NULL OR content_key = '')
        """
      ).fetchall()
      for row in rows:
        key = by_id.get(row["bundle_id"])
        if not key:
          continue
        conn.execute(
          "UPDATE ig_posts SET content_key = ? WHERE bundle_id = ? AND kind = ?",
          (key, row["bundle_id"], row["kind"]),
        )
        updated += 1
    return updated

  def mark_failed(self, bundle_id: str, kind: str, error: str) -> None:
    with self._conn() as conn:
      conn.execute(
        """
        INSERT INTO ig_posts (bundle_id, kind, ig_media_id, posted_at, error, content_key)
        VALUES (?, ?, NULL, NULL, ?, NULL)
        ON CONFLICT(bundle_id, kind) DO UPDATE SET error = excluded.error
        """,
        (bundle_id, kind, error[:500]),
      )
