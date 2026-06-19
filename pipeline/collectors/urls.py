"""GeekNews URL 정규화·중복 키."""

from __future__ import annotations

import re


def extract_topic_id(url: str) -> str | None:
    match = re.search(r"topic[?]id=(\d+)", url)
    return match.group(1) if match else None


def canonical_post_url(url: str) -> str:
    topic_id = extract_topic_id(url)
    if topic_id:
        return f"https://news.hada.io/topic?id={topic_id}"
    return url.strip().rstrip("/")


def dedup_key_for_url(url: str) -> str:
    topic_id = extract_topic_id(url)
    if topic_id:
        return f"topic:{topic_id}"
    return f"url:{canonical_post_url(url)}"


def expand_url_variants(urls: set[str]) -> set[str]:
    expanded: set[str] = set()
    for url in urls:
        expanded.add(url)
        expanded.add(canonical_post_url(url))
    return expanded
