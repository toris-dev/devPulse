#!/usr/bin/env bash
# Instagram 미디어용 로컬 HTTP 서버(9088)를 공개 HTTPS로 노출
set -euo pipefail

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared 설치: brew install cloudflared"
  exit 1
fi

PORT="${IG_MEDIA_PORT:-9088}"
echo "→ 미디어 서버 포트 ${PORT} 터널 시작"
echo "→ 출력 URL을 infra/.env.instagram 의 MINIO_PUBLIC_ENDPOINT 에 설정"
echo "   (릴스 영상 서빙용 URL — MINIO_PUBLIC_ENDPOINT 에 설정)"
echo ""

cloudflared tunnel --url "http://localhost:${PORT}"
