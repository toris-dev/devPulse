import re
from typing import Any

from pipeline.collectors.urls import canonical_post_url, dedup_key_for_url


def normalize_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^(Ask GN|Show GN)\s*[-:]\s*", "", title, flags=re.IGNORECASE)
    return title


def normalize_post(post: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(post)
    normalized["title"] = normalize_title(post.get("title", ""))
    normalized["url"] = canonical_post_url(post.get("url", ""))
    normalized["dedup_key"] = dedup_key_for_url(normalized["url"])
    return normalized


def deduplicate_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for post in posts:
        key = post.get("dedup_key") or dedup_key_for_url(post.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(post)
    return unique
