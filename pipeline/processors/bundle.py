import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.types.json import Json

from pipeline.lib import db, minio_client
from pipeline.lib.log import log
from pipeline.lib.progress import get_tracker
from pipeline.processors.card_news import CARD_EXT, card_path_for_post
from pipeline.processors.bundle_video import generate_bundle_video
from pipeline.publishers.sns import publish_bundle


def get_bundle_size() -> int:
    return int(os.getenv("BUNDLE_SIZE", "6"))


def bundle_pad_enabled() -> bool:
    return os.getenv("BUNDLE_ALLOW_PAD", "0").strip().lower() in ("1", "true", "yes", "on")


def bundle_min_cards() -> int:
    return max(1, int(os.getenv("BUNDLE_MIN_CARDS", "1")))


def can_run_bundle(card_backlog: int) -> bool:
    """번들 생성 가능 여부 (6장 미만이면 BUNDLE_ALLOW_PAD 필요)."""
    size = get_bundle_size()
    if card_backlog < bundle_min_cards():
        return False
    if card_backlog >= size:
        return True
    return bundle_pad_enabled()


def get_card_seconds() -> int:
    return int(os.getenv("BUNDLE_CARD_SECONDS", "5"))


def _make_bundle_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"bundle-{ts}"


def run_bundle_publish(
    posts: list[dict[str, Any]],
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    if not posts:
        raise ValueError("posts is empty")

    bundle_id = _make_bundle_id()
    out = output_dir or Path("./output")
    bundle_dir = out / "bundles" / bundle_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    tracker = get_tracker()
    tracker.set_phase("번들", step=f"{len(posts)}장 묶음", post_id=bundle_id)

    card_paths: list[Path] = []
    card_keys: list[str] = []
    items: list[dict[str, Any]] = []

    for i, post in enumerate(posts, start=1):
        post_id = post["id"]
        src = card_path_for_post(out / "cards", post_id)
        if not src.exists():
            raise FileNotFoundError(f"카드 없음: {out / 'cards' / f'{post_id}.{CARD_EXT}'}")

        dst = bundle_dir / "cards" / f"{i:02d}-{post_id}.{CARD_EXT}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        card_paths.append(dst)
        card_keys.append(post.get("card_image_key") or f"cards/{post_id}.{CARD_EXT}")

        summary = post.get("llm_summary") or {}
        if isinstance(summary, str):
            summary = {}
        items.append({"post": post, "summary": summary, "card_path": dst})

    if verbose:
        log(f"번들 {bundle_id}: 카드 {len(card_paths)}장 준비")

    tracker.set_phase("번들", step="쇼츠 생성", post_id=bundle_id)
    video_path = bundle_dir / f"{bundle_id}.mp4"
    video_key: str | None = None

    try:
        if verbose:
            log(f"  [{bundle_id}] 번들 영상 생성 중...")
        generate_bundle_video(card_paths, video_path, seconds_per_card=get_card_seconds())
        video_key = f"bundles/{bundle_id}/{bundle_id}.mp4"
        minio_client.upload_file(video_path, video_key, "video/mp4")
        if verbose:
            log(f"  [{bundle_id}] 영상 저장: {video_path}")
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        if verbose:
            log(f"  [{bundle_id}] 영상 스킵: {exc}")

    tracker.set_phase("번들", step="SNS 게시", post_id=bundle_id)
    if verbose:
        log(f"  [{bundle_id}] SNS 번들 게시 중...")
    sns_result = publish_bundle(bundle_id, items, card_paths=card_paths, video_path=video_path)

    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO content_bundles (id, post_ids, card_keys, video_key, sns_meta)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (bundle_id, [p["id"] for p in posts], card_keys, video_key, Json(sns_result)),
        )
        for post in posts:
            db.update_post_status(
                conn,
                post["id"],
                "published",
                extra={
                    "bundle_id": bundle_id,
                    "video_key": video_key,
                    "sns_post_id": sns_result.get("bundle_id"),
                    "sns_posted_at": sns_result.get("published_at"),
                },
            )
        conn.commit()

    if verbose:
        log(f"번들 완료: {bundle_id} → {len(posts)}건 published")

    return {
        "bundle_id": bundle_id,
        "post_ids": [p["id"] for p in posts],
        "card_count": len(card_paths),
        "video_key": video_key,
        "video_path": str(video_path) if video_path.exists() else None,
        "sns": sns_result,
    }


def run_pending_bundles(*, verbose: bool = True) -> list[dict[str, Any]]:
    bundle_size = get_bundle_size()
    results: list[dict[str, Any]] = []
    while True:
        with db.get_conn() as conn:
            posts = db.fetch_posts_by_status(conn, "card_generated", limit=bundle_size)

        if len(posts) < bundle_size:
            if not posts:
                break
            if bundle_pad_enabled() and len(posts) >= bundle_min_cards():
                padded: list[dict[str, Any]] = []
                while len(padded) < bundle_size:
                    padded.extend(posts)
                posts = padded[:bundle_size]
                if verbose:
                    log(
                        f"번들 대기: {len(posts)}/{bundle_size}장 미만 — 카드 반복 패딩으로 생성합니다."
                    )
            else:
                if verbose:
                    log(f"번들 대기: {len(posts)}/{bundle_size}장 (추가 수집 필요)")
                break

        result = run_bundle_publish(posts, verbose=verbose)
        results.append(result)

    return results
