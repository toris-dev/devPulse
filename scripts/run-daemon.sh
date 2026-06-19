#!/usr/bin/env bash
# 파이프라인 데몬 (+ DASHBOARD_ENABLED=1 이면 웹 대시보드 동시 실행)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONUNBUFFERED=1

if [[ ! -d .venv ]]; then
  echo "ERROR: .venv 없음. python3 -m venv .venv && pip install -e ."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
exec python -u scripts/run_daemon.py "$@"
