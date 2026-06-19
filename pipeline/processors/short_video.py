import shutil
import subprocess
from pathlib import Path
from typing import Any


def generate_short_video(
    card_png_path: Path,
    summary: dict[str, Any],
    output_path: Path,
    *,
    duration: int = 30,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg locally or run inside Docker "
            "(docker compose --profile pipeline run pipeline python -m pipeline.cli run)"
        )

    # 카드뉴스 PNG에 텍스트가 포함되어 있어 drawtext 없이 줌 효과만 적용
    vf_parts = [
        "scale=1080:1920:force_original_aspect_ratio=decrease",
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0f1117",
        "zoompan=z='min(zoom+0.0008,1.08)':d=900:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920",
    ]

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(card_png_path),
        "-vf",
        ",".join(vf_parts),
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        str(output_path),
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return output_path
