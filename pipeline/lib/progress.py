import json
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ProgressState:
    daemon_status: str = "idle"
    run_number: int = 0
    phase: str = "대기"
    step: str = ""
    current_post_id: str = ""
    current_title: str = ""
    collected_this_run: int = 0
    queue_size: int = 0
    processed_this_run: int = 0
    failed_this_run: int = 0
    total_published: int = 0
    total_collected: int = 0
    total_failed: int = 0
    sleep_seconds: int = 0
    ends_at: str = ""
    started_at: str = ""
    updated_at: str = ""
    recent_logs: list[str] = field(default_factory=list)


class ProgressTracker:
    def __init__(self, state_file: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._state = ProgressState()
        self._logs: deque[str] = deque(maxlen=100)
        self.state_file = state_file or Path("output/progress.json")

    def snapshot(self) -> ProgressState:
        with self._lock:
            return ProgressState(**asdict(self._state))

    def configure(
        self,
        *,
        ends_at: datetime,
        started_at: datetime,
        sleep_seconds: int = 0,
    ) -> None:
        with self._lock:
            self._state.ends_at = ends_at.isoformat()
            self._state.started_at = started_at.isoformat()
            self._state.sleep_seconds = sleep_seconds
            self._persist()

    def set_daemon(self, status: str, *, run_number: int | None = None) -> None:
        with self._lock:
            self._state.daemon_status = status
            if run_number is not None:
                self._state.run_number = run_number
            self._touch()
            self._persist()

    def set_phase(
        self,
        phase: str,
        *,
        step: str = "",
        post_id: str = "",
        title: str = "",
    ) -> None:
        with self._lock:
            self._state.phase = phase
            self._state.step = step
            self._state.current_post_id = post_id
            self._state.current_title = title
            self._touch()
            self._persist()

    def set_run_stats(
        self,
        *,
        collected: int | None = None,
        queue_size: int | None = None,
        processed: int | None = None,
        failed: int | None = None,
    ) -> None:
        with self._lock:
            if collected is not None:
                self._state.collected_this_run = collected
            if queue_size is not None:
                self._state.queue_size = queue_size
            if processed is not None:
                self._state.processed_this_run = processed
            if failed is not None:
                self._state.failed_this_run = failed
            self._touch()
            self._persist()

    def set_db_stats(self, *, published: int, collected: int, failed: int) -> None:
        with self._lock:
            self._state.total_published = published
            self._state.total_collected = collected
            self._state.total_failed = failed
            self._touch()
            self._persist()

    def add_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts} {msg}"
        with self._lock:
            self._logs.append(line)
            self._state.recent_logs = list(self._logs)
            self._touch()
            self._persist()

    def reset_run_counters(self) -> None:
        with self._lock:
            self._state.collected_this_run = 0
            self._state.queue_size = 0
            self._state.processed_this_run = 0
            self._state.failed_this_run = 0
            self._state.current_post_id = ""
            self._state.current_title = ""
            self._touch()
            self._persist()

    def load_from_file(self) -> ProgressState | None:
        if not self.state_file.exists():
            return None
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            with self._lock:
                self._state = ProgressState(**data)
                self._logs = deque(data.get("recent_logs", []), maxlen=100)
            return self.snapshot()
        except Exception:
            return None

    def _touch(self) -> None:
        self._state.updated_at = datetime.now().isoformat()

    def _persist(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self._state)
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            from pipeline.web.events import notify_dashboard

            notify_dashboard()
        except Exception:
            pass


_tracker: ProgressTracker | None = None


def get_tracker() -> ProgressTracker:
    global _tracker
    if _tracker is None:
        _tracker = ProgressTracker()
    return _tracker
