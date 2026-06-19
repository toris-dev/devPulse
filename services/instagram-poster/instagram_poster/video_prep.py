"""Instagram Reels 호환 영상 준비."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def _has_audio(path: Path) -> bool:
  if not shutil.which("ffprobe"):
    return True
  result = subprocess.run(
    [
      "ffprobe",
      "-v",
      "error",
      "-select_streams",
      "a",
      "-show_entries",
      "stream=codec_type",
      "-of",
      "csv=p=0",
      str(path),
    ],
    capture_output=True,
    text=True,
  )
  return bool(result.stdout.strip())


def prepare_reel_video(src: Path) -> Path:
  """
  Reels는 AAC 오디오 트랙이 필요한 경우가 많음.
  무음 영상이면 무음 AAC 트랙을 추가해 임시 파일로 반환.
  """
  if _has_audio(src):
    return src
  if not shutil.which("ffmpeg"):
    return src

  tmp = Path(tempfile.mkdtemp(prefix="ig-reel-"))
  out = tmp / src.name
  cmd = [
    "ffmpeg",
    "-y",
    "-i",
    str(src),
    "-f",
    "lavfi",
    "-i",
    "anullsrc=channel_layout=stereo:sample_rate=44100",
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "128k",
    "-movflags",
    "+faststart",
    "-shortest",
    str(out),
  ]
  result = subprocess.run(cmd, capture_output=True, text=True)
  if result.returncode != 0:
    return src
  return out
