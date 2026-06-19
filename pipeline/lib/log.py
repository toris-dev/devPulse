from datetime import datetime
from pathlib import Path

from pipeline.lib.progress import get_tracker

_LOG_PATH = Path("output/daemon.log")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    get_tracker().add_log(msg)
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
