#!/usr/bin/env python3
"""백그라운드 데몬 진행 상황 실시간 모니터 (progress.json 기반)."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_FILE = ROOT / "output" / "progress.json"


def _format_remaining(ends_at: str) -> str:
    if not ends_at:
        return "무제한"
    try:
        end = datetime.fromisoformat(ends_at)
        if end.year >= 9999:
            return "무제한"
        remain = int((end - datetime.now()).total_seconds())
        if remain <= 0:
            return "종료"
        h, rem = divmod(remain, 3600)
        m, _ = divmod(rem, 60)
        return f"{h}시간 {m}분" if h else f"{m}분"
    except Exception:
        return "무제한"


def _render(data: dict) -> str:
    lines = [
        "═" * 60,
        " devPulse Monitor (실시간)",
        "═" * 60,
        f" 상태      : {data.get('daemon_status', '-')}",
        f" 실행 회차  : #{data.get('run_number', 0)}",
        f" 종료 예정  : {_format_remaining(data.get('ends_at', ''))}",
        f" 갱신       : {data.get('updated_at', '-')}",
        "─" * 60,
        f" 현재 단계  : {data.get('phase', '-')}",
        f" 세부 작업  : {data.get('step', '-')}",
        f" 글 ID      : {data.get('current_post_id') or '-'}",
        f" 제목       : {data.get('current_title') or '-'}",
        "─" * 60,
        f" 이번 수집   : {data.get('collected_this_run', 0)}건",
        f" 처리 대기   : {data.get('queue_size', 0)}건",
        f" 이번 처리   : {data.get('processed_this_run', 0)}건",
        f" 이번 실패   : {data.get('failed_this_run', 0)}건",
        "─" * 60,
        f" DB published : {data.get('total_published', 0)}",
        f" DB collected : {data.get('total_collected', 0)}",
        f" DB failed    : {data.get('total_failed', 0)}",
        "─" * 60,
        " 최근 로그",
    ]
    for entry in data.get("recent_logs", [])[-8:]:
        lines.append(f"  {entry}")
    lines.append("═" * 60)
    lines.append(" Ctrl+C 로 종료")
    return "\n".join(lines)


def main() -> None:
    if not PROGRESS_FILE.exists():
        print(f"진행 파일 없음: {PROGRESS_FILE}", file=sys.stderr)
        print("먼저 실행: python scripts/run_daemon.py", file=sys.stderr)
        sys.exit(1)

    try:
        while True:
            data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            sys.stdout.write("\033[H\033[2J\033[3J")
            sys.stdout.write(_render(data))
            sys.stdout.flush()
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n모니터 종료.", file=sys.stderr)


if __name__ == "__main__":
    main()
