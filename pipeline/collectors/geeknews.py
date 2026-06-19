import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
from bs4 import BeautifulSoup

GEEKNEWS_FEEDS: dict[str, str] = {
    "all": "https://news.hada.io/rss/news",
    "new": "https://itcord.github.io/geeknews/new.xml",
    "ask": "https://itcord.github.io/geeknews/ask.xml",
    "show": "https://itcord.github.io/geeknews/show.xml",
    "top": "https://itcord.github.io/geeknews/home.xml",
}

FETCH_DELAY_SEC = float(os.getenv("GEEKNEWS_FETCH_DELAY", "0.3"))


def _collect_workers() -> int:
    return max(1, int(os.getenv("COLLECT_WORKERS", "4")))


def _parse_datetime(entry: dict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


from pipeline.collectors.urls import canonical_post_url, dedup_key_for_url, expand_url_variants, extract_topic_id


def _clean_html(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def _parse_topic_md(md: str) -> str:
    match = re.search(r"## Topic Body\s*\n(.*)", md, re.DOTALL)
    if match:
        body = re.split(r"\n## Comments\b", match.group(1), maxsplit=1)[0]
        return re.sub(r"\n{3,}", "\n\n", body.strip())

    parts = md.split("---", 1)
    if len(parts) > 1:
        return parts[1].strip()
    return md.strip()


def _fetch_full_content(url: str) -> tuple[str | None, str | None]:
    topic_id = extract_topic_id(url)
    if not topic_id:
        return None, None

    md_url = f"https://news.hada.io/topic/{topic_id}.md"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            res = client.get(md_url, headers={"User-Agent": "devPulse/0.1"})
            res.raise_for_status()
            raw_md = res.text
            return _parse_topic_md(raw_md), raw_md
    except Exception:
        return None, None


def _detect_feed_type(title: str, url: str, feed_type: str) -> str:
    if feed_type != "all":
        return feed_type
    lower = title.lower()
    if "ask gn" in lower or "/ask" in url:
        return "ask"
    if "show gn" in lower or "/show" in url:
        return "show"
    return "news"


def _make_post_id(url: str) -> str:
    topic_id = extract_topic_id(url)
    if topic_id:
        return f"geeknews-{topic_id}"
    return f"geeknews-{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def _normalize_post_fields(post: dict[str, Any]) -> dict[str, Any]:
    post = dict(post)
    post["url"] = canonical_post_url(post["url"])
    post["id"] = _make_post_id(post["url"])
    return post


def _enrich_content(link: str, summary_html: str) -> tuple[str | None, str | None]:
    full_text, full_raw = _fetch_full_content(link)
    if full_text:
        if FETCH_DELAY_SEC > 0:
            time.sleep(FETCH_DELAY_SEC)
        return full_text, full_raw

    cleaned = _clean_html(summary_html)
    return (cleaned or None), (summary_html or None)


def _enrich_post(post: dict[str, Any]) -> dict[str, Any]:
    summary_html = post.pop("_summary_html", "") or ""
    summary, raw_content = _enrich_content(post["url"], summary_html)
    post["summary"] = summary
    post["raw_content"] = raw_content
    return post


def parse_feed(feed_type: str, feed_url: str, *, fetch_full: bool = True) -> list[dict[str, Any]]:
    parsed = feedparser.parse(feed_url)
    posts: list[dict[str, Any]] = []

    for entry in parsed.entries:
        link = entry.get("link") or entry.get("id", "")
        if not link:
            continue

        title = entry.get("title", "").strip()
        summary_html = entry.get("summary") or entry.get("content", [{}])[0].get("value", "")
        detected_type = _detect_feed_type(title, link, feed_type)

        if fetch_full:
            summary, raw_content = _enrich_content(link, summary_html)
        else:
            summary = _clean_html(summary_html) or None
            raw_content = summary_html or None

        posts.append(
            {
                "id": _make_post_id(link),
                "source": "GeekNews",
                "feed_type": detected_type,
                "title": title,
                "url": link,
                "summary": summary,
                "raw_content": raw_content,
                "_summary_html": summary_html,
                "author": (entry.get("author") or "").strip() or None,
                "published_at": _parse_datetime(entry),
                "upvotes": None,
                "comments_count": None,
            }
        )

    return posts


def collect_all_feeds(
    feed_types: list[str] | None = None,
    *,
    fetch_full: bool = True,
    skip_urls: set[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = feed_types or list(GEEKNEWS_FEEDS.keys())
    skip = expand_url_variants(skip_urls or set())
    merged: dict[str, dict[str, Any]] = {}
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    feed_jobs = [(ft, GEEKNEWS_FEEDS[ft]) for ft in selected if ft in GEEKNEWS_FEEDS]
    workers = min(_collect_workers(), max(1, len(feed_jobs)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(parse_feed, feed_type, feed_url, fetch_full=False): feed_type
            for feed_type, feed_url in feed_jobs
        }
        for future in as_completed(futures):
            for raw_post in future.result():
                post = _normalize_post_fields(raw_post)
                if post["url"] in skip:
                    continue
                key = dedup_key_for_url(post["url"])
                existing = merged.get(key)
                if existing is None:
                    merged[key] = post
                    continue
                post_dt = post.get("published_at") or min_dt
                existing_dt = existing.get("published_at") or min_dt
                if post_dt >= existing_dt:
                    merged[key] = post

    candidates = list(merged.values())
    candidates.sort(
        key=lambda p: p.get("published_at") or min_dt,
        reverse=True,
    )
    if limit and limit > 0:
        candidates = candidates[:limit]

    if not fetch_full or not candidates:
        for post in candidates:
            post.pop("_summary_html", None)
        return candidates

    enrich_workers = min(_collect_workers(), len(candidates))
    with ThreadPoolExecutor(max_workers=enrich_workers) as pool:
        enriched = list(pool.map(_enrich_post, candidates))
    return enriched
