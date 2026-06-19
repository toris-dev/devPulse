#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/infra"

ENV_FILE=".env.instagram"
EXAMPLE=".env.instagram.example"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "→ $ENV_FILE 없음. 예시 복사: cp $EXAMPLE $ENV_FILE"
  cp "$EXAMPLE" "$ENV_FILE"
  echo "   Meta 앱 토큰을 설정한 뒤 다시 실행하세요."
  exit 1
fi

echo "→ Instagram poster 시작 (output 마운트, 하루 종일 실행)"
docker compose -f docker-compose.instagram.yml up --build
