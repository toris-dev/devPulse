import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def publish_bundle(
    bundle_id: str,
    items: list[dict[str, Any]],
    *,
    card_paths: list[Path] | None = None,
    video_path: Path | None = None,
) -> dict[str, Any]:
    mode = os.getenv("SNS_MODE", "file").lower()
    if mode != "file":
        return _publish_bundle_file(bundle_id, items, card_paths, video_path)
    return _publish_bundle_file(bundle_id, items, card_paths, video_path)


def _build_bundle_caption(bundle_id: str, items: list[dict[str, Any]]) -> str:
    lines = [f"📰 devPulse 개발 뉴스 묶음 ({len(items)}건)", ""]
    for i, item in enumerate(items, start=1):
        post = item["post"]
        summary = item.get("summary") or {}
        headline = summary.get("headline", post["title"])
        lines.append(f"{i}. {headline}")
        lines.append(f"🔗 {post['url']}")
        lines.append("")
    lines.append("#devPulse #개발뉴스 #GeekNews")
    return "\n".join(lines).strip()


def _publish_bundle_file(
    bundle_id: str,
    items: list[dict[str, Any]],
    card_paths: list[Path] | None,
    video_path: Path | None,
) -> dict[str, Any]:
    output_dir = Path(os.getenv("SNS_OUTPUT_DIR", "./output/sns"))
    output_dir.mkdir(parents=True, exist_ok=True)

    caption = _build_bundle_caption(bundle_id, items)
    caption_path = output_dir / f"{bundle_id}.txt"
    caption_path.write_text(caption, encoding="utf-8")

    meta = {
        "bundle_id": bundle_id,
        "platform": "file",
        "type": "bundle",
        "post_count": len(items),
        "post_ids": [item["post"]["id"] for item in items],
        "caption_path": str(caption_path),
        "card_paths": [str(p) for p in (card_paths or [])],
        "video_path": str(video_path) if video_path and video_path.exists() else None,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / f"{bundle_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def publish_post(
    post: dict[str, Any],
    summary: dict[str, Any],
    *,
    card_path: Path | None = None,
    video_path: Path | None = None,
) -> dict[str, Any]:
    mode = os.getenv("SNS_MODE", "file").lower()

    if mode == "mastodon":
        return _publish_mastodon(post, summary, card_path, video_path)
    if mode == "x":
        return _publish_x(post, summary, card_path, video_path)
    return _publish_file(post, summary, card_path, video_path)


def _build_caption(post: dict[str, Any], summary: dict[str, Any]) -> str:
    bullets = "\n".join(f"• {b}" for b in summary.get("bullet_points", [])[:3])
    return (
        f"{summary.get('headline', post['title'])}\n\n"
        f"{summary.get('why_important', '')}\n\n"
        f"{bullets}\n\n"
        f"🔗 {post['url']}\n"
        f"#devPulse #{summary.get('category', 'Tech').replace(' ', '')}"
    )


def _publish_file(
    post: dict[str, Any],
    summary: dict[str, Any],
    card_path: Path | None,
    video_path: Path | None,
) -> dict[str, Any]:
    output_dir = Path(os.getenv("SNS_OUTPUT_DIR", "./output/sns"))
    output_dir.mkdir(parents=True, exist_ok=True)

    post_id = post["id"]
    caption = _build_caption(post, summary)
    caption_path = output_dir / f"{post_id}.txt"
    caption_path.write_text(caption, encoding="utf-8")

    meta = {
        "post_id": post_id,
        "platform": "file",
        "caption_path": str(caption_path),
        "card_path": str(card_path) if card_path else None,
        "video_path": str(video_path) if video_path else None,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / f"{post_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _publish_mastodon(
    post: dict[str, Any],
    summary: dict[str, Any],
    card_path: Path | None,
    video_path: Path | None,
) -> dict[str, Any]:
    instance = os.getenv("MASTODON_INSTANCE", "").rstrip("/")
    token = os.getenv("MASTODON_ACCESS_TOKEN", "")
    if not instance or not token:
        raise ValueError("MASTODON_INSTANCE and MASTODON_ACCESS_TOKEN required")

    caption = _build_caption(post, summary)
    media_ids: list[str] = []

    with httpx.Client(timeout=60.0) as client:
        for media_path in [card_path, video_path]:
            if not media_path or not media_path.exists():
                continue
            with media_path.open("rb") as f:
                res = client.post(
                    f"{instance}/api/v2/media",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (media_path.name, f)},
                )
                res.raise_for_status()
                media_ids.append(str(res.json()["id"]))

        payload: dict[str, Any] = {"status": caption, "visibility": "public"}
        if media_ids:
            payload["media_ids"] = media_ids

        res = client.post(
            f"{instance}/api/v1/statuses",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        res.raise_for_status()
        data = res.json()

    return {
        "post_id": post["id"],
        "platform": "mastodon",
        "sns_post_id": str(data["id"]),
        "url": data.get("url"),
        "published_at": datetime.now(timezone.utc).isoformat(),
    }


def _publish_x(
    post: dict[str, Any],
    summary: dict[str, Any],
    card_path: Path | None,
    video_path: Path | None,
) -> dict[str, Any]:
    required = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(f"X API credentials missing: {', '.join(missing)}")

    raise NotImplementedError(
        "X API v2 media upload requires tweepy or manual OAuth1. "
        "Set SNS_MODE=file or mastodon for MVP testing."
    )
