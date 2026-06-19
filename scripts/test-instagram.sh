#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/infra"

ENV_FILE=".env.instagram"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "→ $ENV_FILE 없음. cp .env.instagram.example .env.instagram 후 토큰 설정"
  exit 1
fi

echo "→ Instagram 테스트 업로드 (릴스 1건, 즉시 종료)"
docker compose -f docker-compose.instagram.yml run --rm instagram-poster python main.py --once
