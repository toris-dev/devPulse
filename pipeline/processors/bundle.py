import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.types.json import Json

from pipeline.lib import db, minio_client
from pipeline.lib.log import log
from pipeline.lib.progress import get_tracker
from pipeline.processors.card_news import CARD_EXT, card_path_for_post, ensure_card_file
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


def _mark_posts_published(
    conn,
    posts: list[dict[str, Any]],
    bundle_id: str,
    *,
    video_key: str | None,
    sns_result: dict[str, Any] | None = None,
) -> None:
    for post in posts:
        extra: dict[str, Any] = {"bundle_id": bundle_id, "video_key": video_key}
        if sns_result:
            extra["sns_post_id"] = sns_result.get("bundle_id", bundle_id)
            extra["sns_posted_at"] = sns_result.get("published_at")
        db.update_post_status(conn, post["id"], "published", extra=extra)


def reconcile_bundle_queue(out: Path, *, verbose: bool = True) -> dict[str, int]:
    """card_generated 큐 정리 — 이미 번들된 글 동기화, 카드 없는 글 복구/제외."""
    cards_dir = out / "cards"
    stats = {"synced_published": 0, "regenerated": 0, "requeued": 0, "failed": 0}

    with db.get_conn() as conn:
        posts = db.fetch_posts_by_status(conn, "card_generated", limit=500)
        for post in posts:
            post_id = post["id"]
            existing = db.find_bundle_for_post(conn, post_id)
            if existing:
                db.update_post_status(
                    conn,
                    post_id,
                    "published",
                    extra={"bundle_id": existing["id"], "video_key": existing.get("video_key")},
                )
                stats["synced_published"] += 1
                if verbose:
                    log(f"  동기화: {post_id} → published (기존 번들 {existing['id']})")
                continue

            if card_path_for_post(cards_dir, post_id).exists():
                continue

            try:
                ensure_card_file(post, cards_dir, verbose=verbose)
                stats["regenerated"] += 1
            except FileNotFoundError:
                db.update_post_status(
                    conn,
                    post_id,
                    "collected",
                    extra={"error_message": "카드 파일 없음 — 재처리 대기"},
                )
                stats["requeued"] += 1
                if verbose:
                    log(f"  재큐: {post_id} (카드·요약 없음 → collected)")
            except Exception as exc:
                db.update_post_status(
                    conn,
                    post_id,
                    "failed",
                    extra={"error_message": f"카드 재생성 실패: {exc}"[:500]},
                )
                stats["failed"] += 1
                if verbose:
                    log(f"  실패: {post_id} | {exc}")

        conn.commit()

    if verbose and any(stats.values()):
        log(
            "번들 큐 정리: "
            f"동기화 {stats['synced_published']}, "
            f"카드 재생성 {stats['regenerated']}, "
            f"재큐 {stats['requeued']}, "
            f"실패 {stats['failed']}"
        )
    return stats


def _prepare_bundle_posts(
    posts: list[dict[str, Any]],
    out: Path,
    *,
    verbose: bool,
) -> list[dict[str, Any]]:
    """카드 파일이 있는 글만 남김. 없으면 재생성 시도, 실패 시 failed 처리."""
    cards_dir = out / "cards"
    ready: list[dict[str, Any]] = []

    with db.get_conn() as conn:
        for post in posts:
            post_id = post["id"]
            try:
                ensure_card_file(post, cards_dir, verbose=verbose)
                ready.append(post)
            except Exception as exc:
                db.update_post_status(
                    conn,
                    post_id,
                    "failed",
                    extra={"error_message": f"번들 카드 준비 실패: {exc}"[:500]},
                )
                if verbose:
                    log(f"  번들 제외: {post_id} | {exc}")
        conn.commit()

    return ready


def _sns_content_key(post_ids: list[str]) -> str:
    return "posts:" + ",".join(sorted(str(p) for p in post_ids))


def _find_sns_bundle_by_post_ids(sns_dir: Path, post_ids: list[str]) -> str | None:
    if not sns_dir.is_dir():
        return None

    import json

    target = _sns_content_key(post_ids)
    for json_path in sns_dir.glob("bundle-*.json"):
        try:
            meta = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        existing = meta.get("post_ids") or []
        if _sns_content_key(existing) == target:
            return json_path.stem
    return None


def _skip_duplicate_bundle(
    posts: list[dict[str, Any]],
    out: Path,
    *,
    verbose: bool,
) -> dict[str, Any] | None:
    """동일 post_ids 번들이 이미 있으면 새 파일 없이 published만 동기화."""
    post_ids = [p["id"] for p in posts]
    bundle_id: str | None = None
    video_key: str | None = None
    sns_meta: dict[str, Any] | None = None

    with db.get_conn() as conn:
        existing = db.find_bundle_by_post_ids(conn, post_ids)
        if existing:
            bundle_id = existing["id"]
            video_key = existing.get("video_key")
            raw_meta = existing.get("sns_meta")
            sns_meta = raw_meta if isinstance(raw_meta, dict) else None
        else:
            sns_bundle_id = _find_sns_bundle_by_post_ids(out / "sns", post_ids)
            if sns_bundle_id:
                bundle_id = sns_bundle_id
                video_key = f"bundles/{sns_bundle_id}/{sns_bundle_id}.mp4"
                sns_path = out / "sns" / f"{sns_bundle_id}.json"
                if sns_path.is_file():
                    import json

                    try:
                        sns_meta = json.loads(sns_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        sns_meta = None

        if not bundle_id:
            return None

        _mark_posts_published(
            conn,
            posts,
            bundle_id,
            video_key=video_key,
            sns_result=sns_meta,
        )
        conn.commit()

    if verbose:
        log(f"중복 번들 스킵: {bundle_id} (post_ids 동일, 새 영상 생성 안 함)")

    return {
        "bundle_id": bundle_id,
        "post_ids": post_ids,
        "card_count": len(posts),
        "video_key": video_key,
        "video_path": None,
        "sns": sns_meta,
        "skipped_duplicate": True,
    }


def run_bundle_publish(
    posts: list[dict[str, Any]],
    output_dir: Path | None = None,
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    if not posts:
        raise ValueError("posts is empty")

    out = output_dir or Path("./output")
    posts = _prepare_bundle_posts(posts, out, verbose=verbose)
    if not posts:
        raise ValueError("번들에 사용할 카드가 없습니다")

    skipped = _skip_duplicate_bundle(posts, out, verbose=verbose)
    if skipped:
        return skipped

    bundle_id = _make_bundle_id()
    bundle_dir = out / "bundles" / bundle_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    tracker = get_tracker()
    tracker.set_phase("번들", step=f"{len(posts)}장 묶음", post_id=bundle_id)

    card_paths: list[Path] = []
    card_keys: list[str] = []
    items: list[dict[str, Any]] = []
    cards_dir = out / "cards"

    for i, post in enumerate(posts, start=1):
        post_id = post["id"]
        src = ensure_card_file(post, cards_dir, verbose=verbose)

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
        _mark_posts_published(conn, posts, bundle_id, video_key=video_key, sns_result=sns_result)
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


def _fetch_bundle_batch(conn, bundle_size: int, out: Path, *, verbose: bool) -> list[dict[str, Any]]:
    """카드 파일이 실제로 있는 card_generated 글만 번들 후보로 선택."""
    cards_dir = out / "cards"
    candidates = db.fetch_posts_by_status(conn, "card_generated", limit=bundle_size * 4)
    ready: list[dict[str, Any]] = []

    for post in candidates:
        if db.find_bundle_for_post(conn, post["id"]):
            continue
        if not card_path_for_post(cards_dir, post["id"]).exists():
            continue
        ready.append(post)
        if len(ready) >= bundle_size:
            break

    if len(ready) < len(candidates) and verbose and len(ready) < bundle_size:
        skipped = len(candidates) - len(ready)
        if skipped:
            log(f"번들 후보 {skipped}건 제외 (이미 번들됨 또는 카드 없음)")

    return ready


def run_pending_bundles(*, verbose: bool = True, output_dir: Path | None = None) -> list[dict[str, Any]]:
    out = output_dir or Path("./output")
    reconcile_bundle_queue(out, verbose=verbose)

    bundle_size = get_bundle_size()
    results: list[dict[str, Any]] = []

    while True:
        with db.get_conn() as conn:
            posts = _fetch_bundle_batch(conn, bundle_size, out, verbose=verbose)

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

        try:
            result = run_bundle_publish(posts, output_dir=out, verbose=verbose)
            results.append(result)
        except ValueError as exc:
            if verbose:
                log(f"번들 중단: {exc}")
            break

    return results
