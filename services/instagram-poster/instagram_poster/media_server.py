"""Instagram용 로컬 정적 미디어 서버 (cloudflared → 9088)."""

from __future__ import annotations

import http.server
import logging
import mimetypes
import os
import shutil
import socketserver
import threading
import uuid
from pathlib import Path
import tempfile

import httpx

from instagram_poster.client import InstagramError

logger = logging.getLogger(__name__)

_MEDIA_ROOT = Path(tempfile.gettempdir()) / "devpulse-ig-media"
_PORT = int(os.getenv("IG_MEDIA_PORT", "9088"))
_server_lock = threading.Lock()
_server_started = False

_VIDEO_TYPES = {
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".webm": "video/webm",
}


class _MediaHandler(http.server.BaseHTTPRequestHandler):
  def do_GET(self) -> None:
    name = self.path.lstrip("/").split("?", 1)[0]
    if not name or ".." in name or "/" in name:
      self.send_error(404)
      return

    path = _MEDIA_ROOT / name
    if not path.is_file():
      self.send_error(404)
      return

    data = path.read_bytes()
    content_type = _VIDEO_TYPES.get(path.suffix.lower()) or (
      mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    self.send_response(200)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Accept-Ranges", "bytes")
    self.send_header("Cache-Control", "public, max-age=3600")
    self.end_headers()
    self.wfile.write(data)

  def log_message(self, format: str, *args) -> None:
    logger.debug("media %s", format % args)


def ensure_media_server() -> None:
  global _server_started
  with _server_lock:
    if _server_started:
      return
    _MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    httpd = socketserver.TCPServer(("0.0.0.0", _PORT), _MediaHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="ig-media-server").start()
    _server_started = True
    logger.info("미디어 서버 시작 http://127.0.0.1:%d", _PORT)


def _public_base() -> str:
  base = os.getenv("IG_MEDIA_PUBLIC_BASE_URL", "").strip() or os.getenv(
    "MINIO_PUBLIC_ENDPOINT", ""
  ).strip()
  if not base:
    raise InstagramError(
      "공개 HTTPS URL 필요:\n"
      "  cloudflared tunnel --url http://localhost:9088\n"
      "  MINIO_PUBLIC_ENDPOINT=https://xxxx.trycloudflare.com"
    )
  return base.rstrip("/")


def _verify_media_url(url: str) -> None:
  try:
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
      res = client.get(
        url,
        headers={
          "User-Agent": "facebookexternalhit/1.1",
          "Accept": "video/*,*/*",
        },
      )
  except httpx.HTTPError as exc:
    raise InstagramError(f"미디어 URL 접근 실패: {exc}") from exc

  ct = (res.headers.get("content-type") or "").lower()
  if res.status_code >= 400:
    raise InstagramError(f"미디어 URL HTTP {res.status_code}")
  if "text/html" in ct:
    raise InstagramError(
      "미디어 URL이 HTML을 반환합니다. cloudflared를 localhost:9088 에 연결했는지 확인하세요."
    )
  if not ct.startswith("video/"):
    raise InstagramError(f"video 아님: {ct}")


def stage_media_url(local_path: Path, *, kind: str) -> str:
  """영상을 로컬 HTTP 서버에 올리고 공개 URL 반환."""
  from instagram_poster.video_prep import prepare_reel_video

  if kind != "video":
    raise InstagramError(f"지원하지 않는 미디어 종류: {kind}")

  ensure_media_server()
  prepared = prepare_reel_video(local_path)
  suffix = prepared.suffix or ".mp4"

  dest = _MEDIA_ROOT / f"{uuid.uuid4().hex}{suffix}"
  shutil.copy2(prepared, dest)

  url = f"{_public_base()}/{dest.name}"
  _verify_media_url(url)
  return url
