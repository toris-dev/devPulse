import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pipeline.collectors.geeknews import collect_all_feeds
from pipeline.lib import db, minio_client
from pipeline.lib.log import log
from pipeline.lib.progress import get_tracker
from pipeline.processors.bundle import can_run_bundle, get_bundle_size, run_pending_bundles
from pipeline.processors.card_news import CARD_EXT, generate_card_jpeg
from pipeline.processors.llm_summary import summarize_post
from pipeline.processors.normalizer import deduplicate_posts, normalize_post


def _refresh_db_stats() -> dict[str, int]:
    with db.get_conn() as conn:
        counts = db.count_posts_by_status(conn)
    get_tracker().set_db_stats(
        published=counts.get("published", 0),
        collected=counts.get("collected", 0),
        failed=counts.get("failed", 0),
    )
    return counts


def _collect_limit(batch_size: int) -> int | None:
    val = int(os.getenv("COLLECT_LIMIT", "0"))
    if val <= 0:
        return None
    return val


def _process_workers() -> int:
    return max(1, int(os.getenv("PROCESS_WORKERS", "2")))


def _process_batch_limit(batch_size: int, backlog: int) -> int:
    cap = int(os.getenv("PROCESS_BATCH_MAX", str(batch_size * _process_workers())))
    return min(backlog, max(batch_size, cap))


def run_collect(
    feed_types: list[str] | None = None,
    limit: int = 20,
    *,
    verbose: bool = True,
    skip_urls: set[str] | None = None,
) -> dict[str, Any]:
    tracker = get_tracker()
    tracker.set_phase("수집", step=f"신규 글만 (limit={limit})")

    if verbose:
        log(f"수집 시작 feeds={feed_types or 'all'} limit={limit}")

    raw_posts = collect_all_feeds(feed_types, skip_urls=skip_urls, limit=limit)
    normalized = [normalize_post(p) for p in raw_posts]
    unique = deduplicate_posts(normalized)
    dup_skipped = len(normalized) - len(unique)

    inserted = 0
    with db.get_conn() as conn:
        for post in unique:
            _id, status = db.upsert_post(conn, post)
            if status == "collected":
                inserted += 1
                tracker.set_phase(
                    "수집",
                    step=f"신규 {inserted}/{len(unique)}",
                    post_id=post["id"],
                    title=post["title"][:40],
                )
                if verbose:
                    log(f"  신규: {post['id']} | {post['title'][:50]}")
            elif verbose:
                log(f"  스킵: {post['id']} (status={status})")
        conn.commit()

    tracker.set_run_stats(collected=inserted)
    _refresh_db_stats()

    if verbose:
        dup_note = f" · 중복 제거 {dup_skipped}건" if dup_skipped else ""
        log(f"수집 완료: RSS {len(unique)}건 · 신규 {inserted}건{dup_note}")

    return {"collected": len(unique), "inserted": inserted}


def run_process_batch(limit: int = 10, *, verbose: bool = True) -> dict[str, Any]:
    tracker = get_tracker()

    with db.get_conn() as conn:
        posts = db.fetch_posts_for_processing(conn, limit=limit)

    tracker.set_run_stats(queue_size=len(posts))
    workers = min(_process_workers(), len(posts)) if posts else 1
    if verbose:
        log(f"처리 대상: {len(posts)}건 (collected + summarized) · workers={workers}")

    processed: list[dict[str, Any]] = []
    failed = 0

    def _handle_success(result: dict[str, Any]) -> None:
        nonlocal processed
        processed.append(result)
        tracker.set_run_stats(processed=len(processed))
        _refresh_db_stats()

    def _handle_failure(post: dict[str, Any], exc: Exception) -> None:
        nonlocal failed
        failed += 1
        tracker.set_run_stats(failed=failed)
        if verbose:
            log(f"처리 실패: {post['id']} | {exc}")
        with db.get_conn() as conn:
            db.update_post_status(
                conn,
                post["id"],
                "failed",
                extra={"error_message": str(exc)[:500]},
            )
            conn.commit()
        _refresh_db_stats()

    if workers <= 1:
        for post in posts:
            try:
                _handle_success(run_process_post(post, verbose=verbose))
            except Exception as exc:
                _handle_failure(post, exc)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(run_process_post, post, verbose=verbose): post for post in posts
            }
            for future in as_completed(futures):
                post = futures[future]
                try:
                    _handle_success(future.result())
                except Exception as exc:
                    _handle_failure(post, exc)

    bundles = run_pending_bundles(verbose=verbose)

    if verbose:
        log(f"처리 완료: 카드 {len(processed)}건, 번들 {len(bundles)}개")

    return {
        "processed": processed,
        "bundles": bundles,
        "count": len(processed),
        "bundle_count": len(bundles),
        "queue": len(posts),
    }


def run_process_post(post: dict[str, Any], output_dir: Path | None = None, *, verbose: bool = True) -> dict[str, Any]:
    """개별 글 → LLM 요약 → 카드뉴스 (번들 대기 상태)."""
    post_id = post["id"]
    title = post["title"][:50]
    tracker = get_tracker()

    tracker.set_phase("처리", step="시작", post_id=post_id, title=post["title"][:40])
    if verbose:
        log(f"처리 시작: {post_id} | {title}")

    out = output_dir or Path("./output")
    out.mkdir(parents=True, exist_ok=True)

    tracker.set_phase("처리", step="LLM 요약", post_id=post_id, title=post["title"][:40])
    if verbose:
        log(f"  [{post_id}] LLM 요약 중...")
    summary = summarize_post(post)
    if verbose:
        log(f"  [{post_id}] 요약 완료 category={summary.get('category')} impact={summary.get('impact_score')}")

    tracker.set_phase("처리", step="카드뉴스", post_id=post_id, title=post["title"][:40])
    if verbose:
        log(f"  [{post_id}] 카드뉴스 생성 중...")
    card_bytes = generate_card_jpeg(post, summary)
    card_key = f"cards/{post_id}.{CARD_EXT}"
    minio_client.upload_bytes(card_bytes, card_key, "image/jpeg")

    card_path = out / "cards" / f"{post_id}.{CARD_EXT}"
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(card_bytes)
    if verbose:
        log(f"  [{post_id}] 카드 저장: {card_path}")

    bundle_size = get_bundle_size()
    with db.get_conn() as conn:
        db.update_post_status(
            conn,
            post_id,
            "card_generated",
            extra={
                "category": summary["category"],
                "difficulty": summary["difficulty"],
                "impact_score": summary["impact_score"],
                "llm_summary": summary,
                "card_image_key": card_key,
            },
        )
        conn.commit()
        pending = db.count_posts_by_status(conn).get("card_generated", 0)

    if verbose:
        log(f"처리 완료: {post_id} → card_generated (번들 대기 {pending}/{bundle_size})")

    return {
        "post_id": post_id,
        "summary": summary,
        "card_key": card_key,
        "card_path": str(card_path),
        "bundle_pending": pending,
    }


def _try_bundle(card_backlog: int, *, verbose: bool) -> list[dict[str, Any]]:
    if not can_run_bundle(card_backlog):
        return []
    tracker = get_tracker()
    size = get_bundle_size()
    if card_backlog >= size:
        step = f"카드 {card_backlog}장 → 번들 생성"
    else:
        step = f"카드 {card_backlog}/{size}장 → 패딩 번들"
    tracker.set_phase("사이클", step=step)
    if verbose:
        log(f"번들 생성 시도: {card_backlog}/{size}장")
    return run_pending_bundles(verbose=verbose)


def run_cycle(
    batch_size: int = 5,
    feed_types: list[str] | None = None,
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    """백로그 처리 → 번들 → 신규 수집 순. RSS 신규 없어도 대기 카드로 번들 생성."""
    tracker = get_tracker()
    tracker.reset_run_counters()
    counts = _refresh_db_stats()
    backlog = counts.get("collected", 0) + counts.get("summarized", 0)
    card_backlog = counts.get("card_generated", 0)

    # 1) collected/summarized 백로그 → 카드 생성
    if backlog > 0:
        tracker.set_phase("사이클", step=f"백로그 {backlog}건 → 처리 우선")
        if verbose:
            log(f"백로그 {backlog}건 — 수집 스킵, 처리만 진행")
        limit = _process_batch_limit(batch_size, backlog)
        result = run_process_batch(limit, verbose=verbose)
        return {"mode": "process", "backlog": backlog, **result}

    # 2) 대기 카드만 있으면 RSS 스캔 전에 번들 시도 (패딩 포함)
    bundles = _try_bundle(card_backlog, verbose=verbose)
    if bundles:
        return {"mode": "bundle", "bundles": bundles, "count": 0, "bundle_count": len(bundles)}

    # 3) 신규 RSS 수집 (DB에 없는 URL만)
    tracker.set_phase("사이클", step="신규 글 RSS 스캔")
    with db.get_conn() as conn:
        known_urls, _full_urls = db.fetch_url_index(conn)

    collect_result = run_collect(
        feed_types=feed_types,
        limit=_collect_limit(batch_size),
        skip_urls=known_urls,
        verbose=verbose,
    )

    if collect_result["inserted"] > 0:
        limit = _process_batch_limit(batch_size, collect_result["inserted"])
        result = run_process_batch(limit, verbose=verbose)
        return {"mode": "collect+process", "collect": collect_result, **result}

    # 4) 신규 글 없음 — 번들 한 번 더 시도 후 유휴
    counts = _refresh_db_stats()
    card_backlog = counts.get("card_generated", 0)
    bundles = _try_bundle(card_backlog, verbose=verbose)
    if bundles:
        return {
            "mode": "bundle",
            "collect": collect_result,
            "bundles": bundles,
            "count": 0,
            "bundle_count": len(bundles),
        }

    tracker.set_phase("유휴", step="신규 글 없음 · 번들 대기 없음")
    if verbose:
        log("유휴 — 신규 RSS 없음, 처리/번들 작업 없음")
    return {"mode": "idle", "collect": collect_result, "count": 0}


def run_pipeline(limit: int = 3, feed_types: list[str] | None = None, *, verbose: bool = True) -> dict[str, Any]:
    """CLI 호환 — run_cycle 위임."""
    if verbose:
        log(f"파이프라인 시작 limit={limit}")
    return run_cycle(batch_size=limit, feed_types=feed_types, verbose=verbose)
