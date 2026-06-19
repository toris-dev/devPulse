import logging
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


class InstagramError(Exception):
  pass


class InstagramClient:
  """Instagram Graph API — Reels."""

  def __init__(
    self,
    *,
    access_token: str,
    ig_user_id: str,
    app_id: str,
    graph_version: str = "v21.0",
    media_url_for: Callable[[Path], str] | None = None,
    dry_run: bool = False,
  ) -> None:
    self.access_token = access_token
    self.ig_user_id = ig_user_id
    self.app_id = app_id
    self.graph_version = graph_version
    self.media_url_for = media_url_for
    self.dry_run = dry_run
    self._use_instagram_host = access_token.startswith("IG")
    host = "graph.instagram.com" if self._use_instagram_host else "graph.facebook.com"
    self.base = f"https://{host}/{graph_version}"
    self._fb_base = f"https://graph.facebook.com/{graph_version}"

  def verify_connection(self) -> dict[str, Any]:
    if self._use_instagram_host:
      return self._request(
        "GET",
        f"{self.base}/me",
        params={
          "fields": "user_id,username,account_type",
          "access_token": self.access_token,
        },
      )
    return self._request(
      "GET",
      f"{self.base}/{self.ig_user_id}",
      params={
        "fields": "username,account_type",
        "access_token": self.access_token,
      },
    )

  def _media_url(self, path: Path, *, kind: str) -> str:
    if not self.media_url_for:
      raise InstagramError("media_url_for 가 설정되지 않았습니다.")
    url = self.media_url_for(path, kind=kind)
    logger.info("  미디어 URL: %s", url[:100] + "..." if len(url) > 100 else url)
    return url

  def _request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
    if self.dry_run and method != "GET":
      logger.info("[DRY RUN] %s %s", method, url)
      return {"id": "dry-run-id"}

    with httpx.Client(timeout=120.0) as client:
      res = client.request(method, url, **kwargs)
      if res.status_code >= 400:
        raise InstagramError(f"{method} {url} → {res.status_code}: {res.text[:500]}")
      data = res.json()
      if "error" in data:
        raise InstagramError(str(data["error"]))
      return data

  def _upload_resumable_facebook(self, path: Path) -> str:
    """Facebook Page Token(EAA) 전용."""
    data = path.read_bytes()
    file_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    session = self._request(
      "POST",
      f"{self._fb_base}/{self.app_id}/uploads",
      params={
        "file_name": path.name,
        "file_length": len(data),
        "file_type": file_type,
        "access_token": self.access_token,
      },
    )
    session_id = session["id"].replace("upload:", "")
    upload = self._request(
      "POST",
      f"{self._fb_base}/upload:{session_id}",
      headers={"Authorization": f"OAuth {self.access_token}", "file_offset": "0"},
      content=data,
    )
    handle = upload.get("h")
    if not handle:
      raise InstagramError(f"upload handle missing: {upload}")
    return handle

  def _wait_container(self, creation_id: str, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
      data = self._request(
        "GET",
        f"{self.base}/{creation_id}",
        params={"fields": "status_code,status", "access_token": self.access_token},
      )
      code = data.get("status_code")
      if code == "FINISHED":
        return
      if code == "ERROR":
        raise InstagramError(
          f"미디어 처리 실패: {data}. 영상은 H.264+AAC·9:16, 공개 video_url 이 필요합니다."
        )
      time.sleep(5)
    raise InstagramError(f"container timeout: {creation_id}")

  def publish_container(self, creation_id: str) -> str:
    self._wait_container(creation_id)
    data = self._request(
      "POST",
      f"{self.base}/{self.ig_user_id}/media_publish",
      data={"creation_id": creation_id, "access_token": self.access_token},
    )
    media_id = data.get("id")
    if not media_id:
      raise InstagramError(f"publish failed: {data}")
    return media_id

  def publish_reel(self, video_path: Path, caption: str) -> str:
    if self.dry_run:
      return "dry-run-reel"

    from instagram_poster.video_prep import prepare_reel_video

    reel_path = prepare_reel_video(video_path)

    if self._use_instagram_host:
      video_url = self._media_url(reel_path, kind="video")
      container = self._request(
        "POST",
        f"{self.base}/{self.ig_user_id}/media",
        data={
          "media_type": "REELS",
          "video_url": video_url,
          "caption": caption[:2200],
          "access_token": self.access_token,
        },
      )
    else:
      handle = self._upload_resumable_facebook(video_path)
      container = self._request(
        "POST",
        f"{self.base}/{self.ig_user_id}/media",
        data={
          "media_type": "REELS",
          "video_id": handle,
          "caption": caption[:2200],
          "access_token": self.access_token,
        },
      )
    return self.publish_container(container["id"])
