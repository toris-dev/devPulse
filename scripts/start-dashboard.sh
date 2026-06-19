#!/usr/bin/env bash
# 대시보드만 단독 실행 (데몬 없이)
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
exec python -m pipeline.cli dashboard "$@"
