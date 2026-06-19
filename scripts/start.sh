#!/usr/bin/env bash
# devPulse 통합 실행: 파이프라인 데몬 + 웹 대시보드
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/run-daemon.sh" "$@"
