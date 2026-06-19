import shutil
import subprocess
from pathlib import Path


def generate_bundle_video(
    card_paths: list[Path],
    output_path: Path,
    *,
    seconds_per_card: int = 5,
) -> Path:
    """카드 PNG N장 → 단일 MP4 슬라이드쇼."""
    if not card_paths:
        raise ValueError("card_paths is empty")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    scale_pad = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0f1117,"
        "setsar=1,fps=30"
    )

    inputs: list[str] = []
    filters: list[str] = []
    n = len(card_paths)

    for i, card in enumerate(card_paths):
        inputs.extend(["-loop", "1", "-t", str(seconds_per_card), "-i", str(card.resolve())])
        filters.append(f"[{i}:v]{scale_pad}[v{i}]")

    concat_inputs = "".join(f"[v{i}]" for i in range(n))
    filters.append(f"{concat_inputs}concat=n={n}:v=1:a=0[outv]")

    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[outv]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )

    return output_path
