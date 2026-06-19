import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BundleJob:
  bundle_id: str
  caption: str
  video_path: Path
  content_key: str
  published_at: str


def content_key_for(meta: dict, video_path: Path) -> str:
  """동일 post_ids·동일 영상은 같은 키 (번들 ID와 무관)."""
  post_ids = meta.get("post_ids")
  if post_ids:
    return "posts:" + ",".join(str(p) for p in post_ids)

  digest = hashlib.sha256()
  with video_path.open("rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
      digest.update(chunk)
  return f"sha256:{digest.hexdigest()}"


def _resolve_path(raw: str, output_dir: Path) -> Path | None:
  path = Path(raw)
  if path.is_absolute() and path.exists():
    return path

  candidates = [
    output_dir.parent / raw,
    output_dir / raw.removeprefix("output/"),
    Path.cwd() / raw,
  ]
  for candidate in candidates:
    if candidate.exists():
      return candidate
  return None


def _read_caption(meta_path: Path, bundle_id: str) -> str:
  txt_path = meta_path.with_suffix(".txt")
  if txt_path.exists():
    return txt_path.read_text(encoding="utf-8").strip()
  return f"📰 devPulse 개발 뉴스 — {bundle_id}\n\n#devPulse #개발뉴스 #GeekNews"


def discover_bundles(sns_dir: Path, output_dir: Path) -> list[BundleJob]:
  if not sns_dir.exists():
    return []

  jobs: list[BundleJob] = []
  for meta_path in sorted(sns_dir.glob("bundle-*.json")):
    try:
      meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
      continue

    bundle_id = meta.get("bundle_id") or meta_path.stem
    video_path = None
    if meta.get("video_path"):
      video_path = _resolve_path(meta["video_path"], output_dir)

    if not video_path:
      fallback = output_dir / "bundles" / bundle_id / f"{bundle_id}.mp4"
      video_path = fallback if fallback.exists() else None

    if not video_path:
      continue

    jobs.append(
      BundleJob(
        bundle_id=bundle_id,
        caption=_read_caption(meta_path, bundle_id),
        video_path=video_path,
        content_key=content_key_for(meta, video_path),
        published_at=meta.get("published_at", ""),
      )
    )

  jobs.sort(key=lambda j: j.published_at or j.bundle_id)
  return jobs
