"""SSE 실시간 스트림."""

from __future__ import annotations

import json
import queue
import time
from collections.abc import Iterator
from pathlib import Path

from pipeline.web.events import get_event_bus
from pipeline.web.status import build_dashboard_payload

_HEARTBEAT_SEC = 15.0


def _format_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def sse_stream(*, root: Path | None = None) -> Iterator[str]:
    bus = get_event_bus()
    sub = bus.subscribe()
    progress_file = (root or Path(".")) / "output" / "progress.json"
    last_mtime = progress_file.stat().st_mtime if progress_file.exists() else 0.0

    try:
        yield _format_sse(build_dashboard_payload())
        last_heartbeat = time.monotonic()
        while True:
            signaled = False
            try:
                sub.get(timeout=0.35)
                signaled = True
            except queue.Empty:
                pass

            file_changed = False
            if progress_file.exists():
                mtime = progress_file.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    file_changed = True

            now = time.monotonic()
            if signaled or file_changed:
                yield _format_sse(build_dashboard_payload())
                last_heartbeat = now
            elif now - last_heartbeat >= _HEARTBEAT_SEC:
                yield ": keepalive\n\n"
                last_heartbeat = now
    finally:
        bus.unsubscribe(sub)
