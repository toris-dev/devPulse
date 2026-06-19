#!/usr/bin/env python3
"""devPulse 연속 실행 데몬 — 백로그 우선, 적응형 대기."""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from pipeline.lib.venv import ensure_project_venv

ensure_project_venv(module_file=Path(__file__))

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["DEVPULSE_TUI"] = "1"
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from pipeline.lib.env import get_daemon_config, load_env
from pipeline.lib.progress import get_tracker
from pipeline.runner import run_cycle


def _check_llm(base_url: str) -> None:
    import httpx

    url = f"{base_url}/models"
    try:
        httpx.get(url, timeout=10.0).raise_for_status()
        return
    except Exception as exc:
        print(f"ERROR: LM Studio 서버 응답 없음 ({url})", file=sys.stderr)
        print(f"  원인: {exc}", file=sys.stderr)
        print("  해결: ./scripts/start-lmstudio-server.sh", file=sys.stderr)
        print("  모델 다운로드: lms get <repo> --gguf -y", file=sys.stderr)
        sys.exit(1)


def _uptime(started_at: str) -> str:
    if not started_at:
        return "-"
    try:
        start = datetime.fromisoformat(started_at)
        elapsed = int((datetime.now() - start).total_seconds())
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        return f"{h}시간 {m}분" if h else f"{m}분 {s}초"
    except Exception:
        return "-"


def _format_remaining(ends_at: str) -> str:
    if not ends_at:
        return "무제한 (Ctrl+C 종료)"
    try:
        end = datetime.fromisoformat(ends_at)
        if end.year >= 9999:
            return "무제한 (Ctrl+C 종료)"
        remain = int((end - datetime.now()).total_seconds())
        if remain <= 0:
            return "종료 예정"
        h, rem = divmod(remain, 3600)
        m, _ = divmod(rem, 60)
        return f"{h}시간 {m}분" if h else f"{m}분"
    except Exception:
        return "무제한"


def _render(state, cfg) -> str:
    lines = [
        "═" * 60,
        " devPulse Pipeline Daemon",
        "═" * 60,
        f" 상태      : {state.daemon_status}",
        f" 실행 회차  : #{state.run_number}",
        f" 가동 시간  : {_uptime(state.started_at)}",
        f" 종료 예정  : {_format_remaining(state.ends_at)}",
        "─" * 60,
        f" batch      : {cfg.batch_size}  idle : {cfg.idle_poll_sec}s  backlog : {cfg.backlog_pause_sec}s",
        f" feeds      : {' '.join(cfg.feeds)}",
        f" llm provider: {cfg.llm_provider}",
        f" llm profile  : {cfg.llm_profile}",
        f" llm model    : {cfg.llm_model}",
        "─" * 60,
        f" 현재 단계  : {state.phase}",
        f" 세부 작업  : {state.step}",
        f" 글 ID      : {state.current_post_id or '-'}",
        f" 제목       : {state.current_title or '-'}",
        "─" * 60,
        f" 이번 수집   : {state.collected_this_run}건",
        f" 처리 대기   : {state.queue_size}건",
        f" 이번 처리   : {state.processed_this_run}건",
        f" 이번 실패   : {state.failed_this_run}건",
        "─" * 60,
        f" DB published : {state.total_published}",
        f" DB collected : {state.total_collected}",
        f" DB failed    : {state.total_failed}",
        "─" * 60,
        " 최근 로그",
    ]
    for entry in state.recent_logs[-20:]:
        lines.append(f"  {entry}")
    lines.append("═" * 60)
    lines.append(" Ctrl+C 로 중단")
    return "\n".join(lines)


class LiveDisplay:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _loop(self) -> None:
        while not self._stop.is_set():
            state = get_tracker().snapshot()
            sys.stdout.write("\033[H\033[2J\033[3J")
            sys.stdout.write(_render(state, self.cfg))
            sys.stdout.flush()
            time.sleep(0.5)


def _cycle_pause_sec(result: dict, cfg) -> int:
    """신규 글 없을 때만 긴 대기, 작업 있으면 즉시(또는 backlog_pause) 다음 사이클."""
    if result.get("mode") == "idle":
        return cfg.idle_poll_sec
    if result.get("count", 0) > 0:
        return cfg.backlog_pause_sec
    if result.get("bundle_count", 0) > 0:
        return cfg.backlog_pause_sec
    collect = result.get("collect") or {}
    if collect.get("inserted", 0) > 0:
        return cfg.backlog_pause_sec
    if result.get("mode") in ("process", "bundle", "collect+process"):
        return cfg.backlog_pause_sec
    return cfg.backlog_pause_sec


def _sleep_countdown(seconds: int, tracker, run_no: int) -> None:
    if seconds <= 0:
        return
    tracker.set_daemon("대기", run_number=run_no)
    for remaining in range(seconds, 0, -1):
        tracker.set_phase("대기", step=f"{remaining}초 후 다음 사이클")
        time.sleep(1)


def _pause_between_cycles(result: dict, cfg, tracker, run_no: int) -> None:
    pause = _cycle_pause_sec(result, cfg)
    if pause <= 0:
        tracker.set_phase("대기", step="즉시 다음 사이클")
        return
    if result.get("mode") == "idle" or pause >= 5:
        _sleep_countdown(pause, tracker, run_no)
    else:
        tracker.set_phase("대기", step=f"{pause}초 후 다음 사이클")
        time.sleep(pause)


def _dashboard_enabled() -> bool:
    return os.getenv("DASHBOARD_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def main() -> None:
    load_env(override=True)
    cfg = get_daemon_config()
    _check_llm(cfg.llm_base_url)

    started = datetime.now()
    ends: datetime | None = None
    if cfg.duration_hours > 0:
        ends = started + timedelta(hours=cfg.duration_hours)

    tracker = get_tracker()
    tracker.configure(
        ends_at=ends or datetime.max,
        started_at=started,
        sleep_seconds=cfg.idle_poll_sec,
    )
    tracker.set_daemon("시작")
    tracker.add_log(
        f"batch={cfg.batch_size} idle={cfg.idle_poll_sec}s "
        f"backlog_pause={cfg.backlog_pause_sec}s feeds={' '.join(cfg.feeds)}"
    )

    use_dashboard = _dashboard_enabled()
    display: LiveDisplay | None = None
    if use_dashboard:
        from pipeline.web.server import start_dashboard_background, stop_dashboard

        dash_url = start_dashboard_background()
        tracker.add_log(f"dashboard: {dash_url}")
    else:
        display = LiveDisplay(cfg)
        display.start()

    run_no = 0

    try:
        while ends is None or datetime.now() < ends:
            run_no += 1
            tracker.reset_run_counters()
            tracker.set_daemon("실행 중", run_number=run_no)

            try:
                result = run_cycle(batch_size=cfg.batch_size, feed_types=cfg.feeds, verbose=True)
                mode = result.get("mode", "?")
                count = result.get("count", 0)
                tracker.add_log(f"cycle #{run_no} {mode} processed={count}")
            except Exception as exc:
                tracker.add_log(f"cycle #{run_no} FAILED: {exc}")
                _sleep_countdown(min(cfg.idle_poll_sec, 30), tracker, run_no)
                continue

            if ends and datetime.now() >= ends:
                break

            _pause_between_cycles(result, cfg, tracker, run_no)

        tracker.set_daemon("종료", run_number=run_no)
        tracker.set_phase("종료", step=f"총 {run_no}회 사이클")
        time.sleep(1)
    except KeyboardInterrupt:
        tracker.set_daemon("중단", run_number=run_no)
        tracker.add_log("사용자 중단")
        time.sleep(0.5)
    finally:
        if display is not None:
            display.stop()
        if use_dashboard:
            from pipeline.web.server import stop_dashboard

            stop_dashboard()


if __name__ == "__main__":
    main()
