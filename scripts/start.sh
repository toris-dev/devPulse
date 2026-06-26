#!/usr/bin/env bash
# devPulse 통합 실행: 미디어 터널 + 파이프라인 데몬 + 웹 대시보드
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

TUNNEL_PID_FILE="${TMPDIR:-/tmp}/devpulse-media-tunnel/cloudflared.pid"

cleanup() {
  if [[ -f "$TUNNEL_PID_FILE" ]]; then
    pid="$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  fi
}

trap cleanup EXIT INT TERM

"$ROOT/scripts/start-media-tunnel.sh" --background
"$ROOT/scripts/run-daemon.sh" "$@"
