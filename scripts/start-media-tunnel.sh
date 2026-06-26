#!/usr/bin/env bash
# Instagram 미디어용 로컬 HTTP 서버(9088)를 공개 HTTPS로 노출
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/infra/.env.instagram"
EXAMPLE_FILE="$ROOT/infra/.env.instagram.example"
RUNTIME_DIR="${TMPDIR:-/tmp}/devpulse-media-tunnel"
PID_FILE="$RUNTIME_DIR/cloudflared.pid"
LOG_FILE="$RUNTIME_DIR/cloudflared.log"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared 설치: brew install cloudflared"
  exit 1
fi

PORT="${IG_MEDIA_PORT:-9088}"
MODE="${1:-foreground}"

mkdir -p "$RUNTIME_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$EXAMPLE_FILE" ]]; then
    cp "$EXAMPLE_FILE" "$ENV_FILE"
    echo "→ infra/.env.instagram 생성"
  else
    echo "infra/.env.instagram.example 없음"
    exit 1
  fi
fi

upsert_env() {
  local key="$1"
  local value="$2"
  local file="$3"
  local tmp
  tmp="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { done = 0 }
    index($0, key "=") == 1 {
      print key "=" value
      done = 1
      next
    }
    { print }
    END {
      if (!done) print key "=" value
    }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

extract_url() {
  if [[ -f "$LOG_FILE" ]]; then
    grep -aoE 'https://[-[:alnum:]]+\.trycloudflare\.com' "$LOG_FILE" | tail -n 1 || true
  fi
}

wait_for_url() {
  local url=""
  local i
  for i in {1..60}; do
    url="$(extract_url)"
    if [[ -n "$url" ]]; then
      printf '%s\n' "$url"
      return 0
    fi
    sleep 1
  done
  return 1
}

write_env_urls() {
  local url="$1"
  upsert_env "MINIO_PUBLIC_ENDPOINT" "$url" "$ENV_FILE"
  upsert_env "IG_MEDIA_PUBLIC_BASE_URL" "$url" "$ENV_FILE"
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

start_background() {
  if is_running; then
    local running_url
    running_url="$(extract_url)"
    if [[ -n "$running_url" ]]; then
      write_env_urls "$running_url"
      echo "→ 기존 미디어 터널 재사용: $running_url"
      echo "→ infra/.env.instagram 갱신 완료"
      return 0
    fi
  fi

  : > "$LOG_FILE"
  rm -f "$PID_FILE"

  echo "→ 미디어 서버 포트 ${PORT} 터널 시작 (background)"
  cloudflared tunnel \
    --url "http://localhost:${PORT}" \
    --no-autoupdate \
    --logfile "$LOG_FILE" \
    --pidfile "$PID_FILE" \
    >/dev/null 2>&1 &

  local url=""
  if ! url="$(wait_for_url)"; then
    echo "cloudflared URL 추출 실패. 로그 확인: $LOG_FILE"
    tail -n 40 "$LOG_FILE" || true
    exit 1
  fi

  write_env_urls "$url"
  echo "→ Cloudflare URL: $url"
  echo "→ infra/.env.instagram 자동 갱신 완료"
}

if [[ "$MODE" == "--background" || "$MODE" == "background" ]]; then
  start_background
  exit 0
fi

echo "→ 미디어 서버 포트 ${PORT} 터널 시작"
echo "→ 로그: $LOG_FILE"
echo "→ 연결 후 infra/.env.instagram 가 자동 갱신됩니다."
echo ""

cloudflared tunnel \
  --url "http://localhost:${PORT}" \
  --no-autoupdate \
  --logfile "$LOG_FILE" \
  --pidfile "$PID_FILE"
