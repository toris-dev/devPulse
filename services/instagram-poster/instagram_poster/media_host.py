"""로컬 영상 파일 → Instagram이 fetch 가능한 공개 URL."""

from __future__ import annotations

from pathlib import Path

from instagram_poster.media_server import stage_media_url


def publishable_url(local_path: Path, *, kind: str | None = None) -> str:
  media_kind = kind or "video"
  return stage_media_url(local_path, kind=media_kind)
