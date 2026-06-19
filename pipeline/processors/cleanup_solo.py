"""개별(1장) 영상·SNS 산출물 정리 — 6장 번들 전용으로 전환."""

from __future__ import annotations

from pathlib import Path

from pipeline.lib import db
from pipeline.lib.env import load_env
from pipeline.lib.log import log


def cleanup_solo_media(*, verbose: bool = True) -> dict:
    load_env()
    root = Path(__file__).resolve().parents[2]
    videos_dir = root / "output" / "videos"
    sns_dir = root / "output" / "sns"

    removed_videos = 0
    if videos_dir.is_dir():
        for path in videos_dir.glob("*.mp4"):
            path.unlink()
            removed_videos += 1
        if not any(videos_dir.iterdir()):
            videos_dir.rmdir()

    removed_sns = 0
    if sns_dir.is_dir():
        for pattern in ("geeknews-*.json", "geeknews-*.txt"):
            for path in sns_dir.glob(pattern):
                path.unlink()
                removed_sns += 1

    with db.get_conn() as conn:
        cleared = db.clear_solo_video_keys(conn)
        conn.commit()

    result = {
        "removed_videos": removed_videos,
        "removed_sns_files": removed_sns,
        "cleared_db_video_keys": cleared,
    }
    if verbose:
        log(
            f"개별 영상 정리: mp4 {removed_videos}개, sns {removed_sns}개, "
            f"DB video_key {cleared}건 초기화"
        )
    return result


if __name__ == "__main__":
    cleanup_solo_media()
