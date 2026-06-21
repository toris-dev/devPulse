"""대시보드용 상태·산출물 수집."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.processors.card_news import card_path_for_post
from pipeline.lib import db
from pipeline.lib.env import load_env
from pipeline.lib.progress import get_tracker
from pipeline.web.instagram import get_instagram_dashboard_info, merge_instagram_status


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _mtime_iso(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _output_url(rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel.startswith("output/"):
        rel = rel[len("output/") :]
    return f"/output/{rel}"


def _fetch_titles(post_ids: list[str]) -> dict[str, str]:
    if not post_ids:
        return {}
    try:
        with db.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, title FROM posts WHERE id = ANY(%s)",
                (post_ids,),
            )
            return {row["id"]: row["title"] for row in cur.fetchall()}
    except Exception:
        return {}


def _list_card_files(cards_dir: Path) -> list[Path]:
    by_stem: dict[str, Path] = {}
    for ext in (".jpg", ".jpeg", ".png"):
        for path in cards_dir.glob(f"*{ext}"):
            prev = by_stem.get(path.stem)
            if prev is None or path.suffix.lower() in (".jpg", ".jpeg"):
                by_stem[path.stem] = path
    return list(by_stem.values())


def _scan_cards(out: Path, *, limit: int = 48) -> list[dict[str, Any]]:
    cards_dir = out / "cards"
    if not cards_dir.is_dir():
        return []

    paths = sorted(_list_card_files(cards_dir), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    post_ids = [p.stem for p in paths]
    titles = _fetch_titles(post_ids)

    items: list[dict[str, Any]] = []
    for p in paths:
        post_id = p.stem
        items.append(
            {
                "post_id": post_id,
                "title": titles.get(post_id, ""),
                "url": _output_url(f"cards/{p.name}"),
                "size_kb": round(p.stat().st_size / 1024, 1),
                "created_at": _mtime_iso(p),
                "kind": "standalone",
            }
        )
    return items


def _content_key(post_ids: list[Any]) -> str:
    if post_ids:
        return "posts:" + ",".join(str(p) for p in post_ids)
    return ""


def _resolve_bundle_video(out: Path, bundle_id: str, meta: dict[str, Any]) -> str | None:
    video_rel = meta.get("video_path", "")
    if video_rel:
        candidate = out / "bundles" / bundle_id / f"{bundle_id}.mp4"
        if not candidate.is_file():
            rel_path = video_rel.replace("\\", "/").removeprefix("output/")
            candidate = out / rel_path
        if candidate.is_file():
            return _output_url(f"bundles/{bundle_id}/{candidate.name}")
    fallback = out / "bundles" / bundle_id / f"{bundle_id}.mp4"
    if fallback.is_file():
        return _output_url(f"bundles/{bundle_id}/{bundle_id}.mp4")
    return None


def _scan_published_bundles(out: Path, *, limit: int = 30) -> dict[str, Any]:
    """완성 번들 — 영상·SNS 메타 통합, post_ids 기준 중복 제거."""
    sns_dir = out / "sns"
    bundles_dir = out / "bundles"
    candidates: list[dict[str, Any]] = []
    seen_bundle_ids: set[str] = set()

    if sns_dir.is_dir():
        for json_path in sorted(sns_dir.glob("bundle-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            bundle_id = json_path.stem
            seen_bundle_ids.add(bundle_id)
            txt_path = sns_dir / f"{bundle_id}.txt"
            try:
                meta = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}

            caption = ""
            if txt_path.is_file():
                try:
                    caption = txt_path.read_text(encoding="utf-8")
                except OSError:
                    caption = ""

            post_ids = meta.get("post_ids", [])
            video_url = _resolve_bundle_video(out, bundle_id, meta)
            if not video_url:
                continue

            bundle_dir = bundles_dir / bundle_id
            cards = sorted(_list_card_files(bundle_dir / "cards")) if (bundle_dir / "cards").is_dir() else []
            video_path = bundle_dir / f"{bundle_id}.mp4"
            size_kb = round(video_path.stat().st_size / 1024, 1) if video_path.is_file() else 0

            candidates.append(
                {
                    "bundle_id": bundle_id,
                    "post_ids": post_ids,
                    "content_key": _content_key(post_ids) or bundle_id,
                    "post_count": meta.get("post_count", len(post_ids)),
                    "platform": meta.get("platform", ""),
                    "published_at": meta.get("published_at", ""),
                    "created_at": _mtime_iso(txt_path if txt_path.is_file() else json_path),
                    "caption": caption,
                    "caption_url": _output_url(f"sns/{bundle_id}.txt"),
                    "json_url": _output_url(f"sns/{bundle_id}.json"),
                    "video_url": video_url,
                    "card_count": len(cards),
                    "size_kb": size_kb,
                }
            )

    if bundles_dir.is_dir():
        for bundle_dir in sorted(bundles_dir.glob("bundle-*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not bundle_dir.is_dir():
                continue
            bundle_id = bundle_dir.name
            if bundle_id in seen_bundle_ids:
                continue
            video = bundle_dir / f"{bundle_id}.mp4"
            if not video.is_file():
                continue
            cards = sorted(_list_card_files(bundle_dir / "cards")) if (bundle_dir / "cards").is_dir() else []
            candidates.append(
                {
                    "bundle_id": bundle_id,
                    "post_ids": [],
                    "content_key": bundle_id,
                    "post_count": len(cards),
                    "platform": "",
                    "published_at": "",
                    "created_at": _mtime_iso(video),
                    "caption": "",
                    "caption_url": None,
                    "json_url": None,
                    "video_url": _output_url(f"bundles/{bundle_id}/{bundle_id}.mp4"),
                    "card_count": len(cards),
                    "size_kb": round(video.stat().st_size / 1024, 1),
                }
            )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        grouped.setdefault(item["content_key"], []).append(item)

    items: list[dict[str, Any]] = []
    for group in grouped.values():
        rep = dict(group[0])
        extras = [g["bundle_id"] for g in group[1:]]
        rep["duplicate_count"] = len(extras)
        if extras:
            rep["duplicate_bundle_ids"] = extras
        items.append(rep)

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {
        "items": items[:limit],
        "raw_count": len(candidates),
        "unique_count": len(items),
    }


def _fetch_bundle_progress(out: Path, bundle_size: int) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    current = 0
    try:
        with db.get_conn() as conn:
            counts = db.count_posts_by_status(conn)
            current = counts.get("card_generated", 0)
            posts = db.fetch_posts_by_status(conn, "card_generated", limit=bundle_size)
            for post in posts:
                post_id = post["id"]
                card_file = card_path_for_post(out / "cards", post_id)
                items.append(
                    {
                        "post_id": post_id,
                        "title": post.get("title", ""),
                        "url": _output_url(f"cards/{card_file.name}") if card_file.is_file() else None,
                    }
                )
    except Exception:
        pass

    target = bundle_size
    pct = round(min(current / target * 100, 100), 1) if target else 0
    return {
        "current": current,
        "target": target,
        "percent": pct,
        "ready": current >= target,
        "slots": _build_bundle_slots(items, target),
        "cards": items,
    }


def _build_bundle_slots(cards: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for i in range(target):
        if i < len(cards):
            c = cards[i]
            slots.append({"index": i + 1, "filled": True, **c})
        else:
            slots.append({"index": i + 1, "filled": False, "post_id": "", "title": "", "url": None})
    return slots


def _read_daemon_log(out: Path, *, tail: int = 200) -> list[str]:
    log_path = out / "daemon.log"
    if not log_path.is_file():
        return []
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-tail:]


def build_dashboard_payload() -> dict[str, Any]:
    load_env()
    root = _root()
    out = root / "output"

    tracker = get_tracker()
    tracker.load_from_file()
    progress = tracker.snapshot()

    db_counts: dict[str, int] = {}
    recent_bundles_db: list[dict[str, Any]] = []
    total_bundles = 0
    try:
        with db.get_conn() as conn:
            db_counts = dict(db.count_posts_by_status(conn))
            cur_total = conn.execute("SELECT COUNT(*) AS c FROM content_bundles")
            total_bundles = int(cur_total.fetchone()["c"] or 0)
            cur = conn.execute(
                """
                SELECT id, post_ids, video_key, created_at
                FROM content_bundles
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
            for row in cur.fetchall():
                recent_bundles_db.append(
                    {
                        "id": row["id"],
                        "post_ids": row["post_ids"],
                        "video_key": row["video_key"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                    }
                )
    except Exception as exc:
        db_counts = {"error": str(exc)}

    cards = _scan_cards(out)
    published = _scan_published_bundles(out)
    instagram = get_instagram_dashboard_info()
    merge_instagram_status(published["items"], instagram)
    bundle_size = int(__import__("os").getenv("BUNDLE_SIZE", "6"))
    bundle_progress = _fetch_bundle_progress(out, bundle_size)
    card_pending = bundle_progress["current"]

    return {
        "progress": {
            "daemon_status": progress.daemon_status,
            "run_number": progress.run_number,
            "phase": progress.phase,
            "step": progress.step,
            "current_post_id": progress.current_post_id,
            "current_title": progress.current_title,
            "collected_this_run": progress.collected_this_run,
            "queue_size": progress.queue_size,
            "processed_this_run": progress.processed_this_run,
            "failed_this_run": progress.failed_this_run,
            "total_published": progress.total_published,
            "total_collected": progress.total_collected,
            "total_failed": progress.total_failed,
            "updated_at": progress.updated_at,
            "recent_logs": progress.recent_logs,
        },
        "db": {
            "counts": db_counts,
            "bundle_pending": f"{card_pending}/{bundle_size}",
            "bundle_total": total_bundles,
            "recent_bundles": recent_bundles_db,
        },
        "bundle": bundle_progress,
        "artifacts": {
            "counts": {
                "cards": len(cards),
                "bundles": published["unique_count"],
                "bundles_raw": published["raw_count"],
            },
            "cards": cards,
            "bundles": published["items"],
        },
        "logs": {
            "tail": _read_daemon_log(out),
            "log_file": "output/daemon.log",
        },
        "instagram": {
            "configured": instagram["configured"],
            "dry_run": instagram["dry_run"],
            "reels_per_day": instagram["reels_per_day"],
            "today_count": instagram["today_count"],
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
