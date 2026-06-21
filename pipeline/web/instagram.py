"""대시보드 ↔ Instagram poster 연동."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from pipeline.web.events import notify_dashboard

_ROOT = Path(__file__).resolve().parents[2]
_IG_SERVICE = _ROOT / "services" / "instagram-poster"
_KIND = "reel"
_imports_ready = False


def _strip_inline_comment(value: str) -> str:
    if "#" not in value:
        return value.strip()
    in_quote = False
    for i, ch in enumerate(value):
        if ch in "\"'":
            in_quote = not in_quote
        elif ch == "#" and not in_quote:
            return value[:i].strip()
    return value.strip()


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def load_instagram_env(*, override: bool = False) -> Path | None:
    """infra/.env.instagram 로드."""
    env_path = _ROOT / "infra" / ".env.instagram"
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _strip_quotes(_strip_inline_comment(value))
        if not key:
            continue
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)

    return env_path


def _resolve_state_db() -> Path:
    load_instagram_env()
    raw = os.getenv("IG_STATE_DB", "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else (_ROOT / raw).resolve()
    output = os.getenv("IG_OUTPUT_DIR", "output").strip()
    out_path = Path(output) if Path(output).is_absolute() else (_ROOT / output).resolve()
    return out_path / "instagram" / "state.db"


def _ensure_ig_imports() -> None:
    global _imports_ready
    if _imports_ready:
        return
    service_path = str(_IG_SERVICE)
    if service_path not in sys.path:
        sys.path.insert(0, service_path)
    _imports_ready = True


def _read_ig_records(state_db: Path) -> list[dict[str, Any]]:
    if not state_db.is_file():
        return []

    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT bundle_id, kind, ig_media_id, posted_at, error, content_key
            FROM ig_posts
            WHERE kind = ?
            """,
            (_KIND,),
        ).fetchall()
    finally:
        conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        ig_media_id = row["ig_media_id"]
        error = row["error"]
        if ig_media_id:
            status = "posted"
        elif error:
            status = "failed"
        else:
            status = "pending"
        records.append(
            {
                "bundle_id": row["bundle_id"],
                "status": status,
                "ig_media_id": ig_media_id,
                "posted_at": row["posted_at"],
                "error": error,
                "content_key": row["content_key"],
            }
        )
    return records


def _count_today(state_db: Path) -> int:
    if not state_db.is_file():
        return 0
    load_instagram_env()
    tz_name = os.getenv("IG_TIMEZONE", "Asia/Seoul")
    try:
        from zoneinfo import ZoneInfo

        day = __import__("datetime").datetime.now(ZoneInfo(tz_name)).date().isoformat()
    except Exception:
        day = __import__("datetime").date.today().isoformat()

    conn = sqlite3.connect(state_db)
    try:
        row = conn.execute(
            "SELECT count FROM ig_daily WHERE day = ? AND kind = ?",
            (day, _KIND),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


def get_instagram_dashboard_info() -> dict[str, Any]:
    load_instagram_env()
    token = os.getenv("IG_ACCESS_TOKEN", "").strip()
    configured = bool(token and os.getenv("IG_USER_ID", "").strip() and os.getenv("IG_APP_ID", "").strip())
    state_db = _resolve_state_db()
    records = _read_ig_records(state_db)

    by_bundle_id = {r["bundle_id"]: r for r in records}
    by_content_key: dict[str, dict[str, Any]] = {}
    for rec in records:
        key = rec.get("content_key")
        if key and rec["status"] == "posted" and key not in by_content_key:
            by_content_key[key] = rec

    return {
        "configured": configured,
        "dry_run": os.getenv("IG_DRY_RUN", "0").strip().lower() in ("1", "true", "yes", "on"),
        "reels_per_day": int(os.getenv("IG_REELS_PER_DAY", "3")),
        "today_count": _count_today(state_db),
        "state_db": str(state_db.relative_to(_ROOT)) if state_db.is_relative_to(_ROOT) else str(state_db),
        "by_bundle_id": by_bundle_id,
        "by_content_key": by_content_key,
    }


def merge_instagram_status(items: list[dict[str, Any]], ig_info: dict[str, Any]) -> None:
    by_bundle = ig_info.get("by_bundle_id") or {}
    by_content = ig_info.get("by_content_key") or {}

    for item in items:
        bundle_id = item.get("bundle_id", "")
        content_key = item.get("content_key", "")

        rec = by_bundle.get(bundle_id)
        if not rec and content_key:
            rec = by_content.get(content_key)

        if rec:
            item["ig"] = {
                "status": rec["status"],
                "ig_media_id": rec.get("ig_media_id"),
                "posted_at": rec.get("posted_at"),
                "error": rec.get("error"),
            }
        else:
            item["ig"] = {"status": "pending", "ig_media_id": None, "posted_at": None, "error": None}


def post_bundle_to_instagram(bundle_id: str, *, ignore_daily_limit: bool = True) -> dict[str, Any]:
    """대시보드에서 번들 1건 Instagram 릴스 업로드."""
    bundle_id = bundle_id.strip()
    if not bundle_id:
        return {"ok": False, "error": "bundle_id 가 필요합니다."}

    load_instagram_env(override=True)
    _ensure_ig_imports()

    from instagram_poster.config import load_config
    from instagram_poster.credentials import validate_credentials
    from instagram_poster.queue import discover_bundles
    from instagram_poster.scheduler import Scheduler

    config = load_config()
    issues = validate_credentials(config)
    if issues:
        return {"ok": False, "error": "; ".join(issues)}

    jobs = discover_bundles(config.sns_dir, config.output_dir)
    job = next((j for j in jobs if j.bundle_id == bundle_id), None)
    if not job:
        return {"ok": False, "error": f"번들을 찾을 수 없습니다: {bundle_id}"}

    scheduler = Scheduler(config)

    if scheduler.store.is_posted(bundle_id, _KIND):
        rec = get_instagram_dashboard_info()["by_bundle_id"].get(bundle_id)
        notify_dashboard()
        return {
            "ok": True,
            "status": "already_posted",
            "bundle_id": bundle_id,
            "ig_media_id": rec.get("ig_media_id") if rec else None,
        }

    if scheduler._skip_duplicate_content(job):
        existing = scheduler.store.find_posted_content(job.content_key, _KIND)
        notify_dashboard()
        return {
            "ok": True,
            "status": "duplicate",
            "bundle_id": bundle_id,
            "ig_media_id": existing.ig_media_id if existing else None,
        }

    if not ignore_daily_limit and scheduler.store.count_today(_KIND) >= config.reels_per_day:
        return {
            "ok": False,
            "error": f"오늘 릴스 한도({config.reels_per_day})에 도달했습니다.",
        }

    client = scheduler._ensure_client()
    try:
        media_id = client.publish_reel(job.video_path, job.caption)
        scheduler.store.mark_posted(job.bundle_id, _KIND, media_id, content_key=job.content_key)
        scheduler.store.increment_today(_KIND)
        notify_dashboard()
        return {
            "ok": True,
            "status": "posted",
            "bundle_id": bundle_id,
            "ig_media_id": media_id,
            "dry_run": config.dry_run,
        }
    except Exception as exc:
        scheduler.store.mark_failed(job.bundle_id, _KIND, str(exc))
        notify_dashboard()
        return {
            "ok": False,
            "status": "failed",
            "bundle_id": bundle_id,
            "error": str(exc),
        }
