#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.lmstudio/bin:${PATH}"

_load_env_var() {
  local key="$1"
  local line val
  line=$(grep -E "^${key}=" infra/.env 2>/dev/null | head -1 || true)
  [[ -z "$line" ]] && return 0
  val="${line#*=}"
  val="${val%%#*}"
  val="${val#\"}"
  val="${val%\"}"
  val="${val#\'}"
  val="${val%\'}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  if [[ -n "$val" ]]; then
    export "${key}=${val}"
  fi
}

if [[ -f infra/.env ]]; then
  _load_env_var LLM_PROFILE
  _load_env_var LLM_MODEL
  _load_env_var LLM_PORT
  _load_env_var LLM_CONTEXT_LENGTH
  _load_env_var MLX_LM_PROFILE
  _load_env_var MLX_LM_MODEL
  _load_env_var MLX_LM_PORT
fi

_resolve_model() {
  python3 -c "
import sys
sys.path.insert(0, '.')
from pipeline.lib.env import load_env, get_llm_model_id
load_env(override=True)
print(get_llm_model_id())
" 2>/dev/null || true
}

MODEL="$(_resolve_model)"
MODEL="${MODEL:-${LLM_MODEL:-${MLX_LM_MODEL:-lmstudio-community/gemma-3-12b-it-GGUF}}}"
PORT="${LLM_PORT:-${MLX_LM_PORT:-1234}}"
CTX="${LLM_CONTEXT_LENGTH:-8192}"
HEALTH_URL="http://127.0.0.1:${PORT}/v1/models"

if ! command -v lms >/dev/null 2>&1; then
  echo "ERROR: lms CLI 없음. LM Studio 설치 후 ~/.lmstudio/bin 이 PATH에 있어야 합니다."
  echo "  https://lmstudio.ai"
  exit 1
fi

_is_healthy() {
  curl -sf --max-time 5 "${HEALTH_URL}" >/dev/null 2>&1
}

_ensure_server() {
  if _is_healthy; then
    return 0
  fi
  echo "LM Studio 서버 시작 중 (port ${PORT})..."
  lms server start --port "${PORT}" --bind 127.0.0.1
  for _ in $(seq 1 30); do
    if _is_healthy; then
      return 0
    fi
    sleep 1
  done
  echo "ERROR: LM Studio 서버가 ${HEALTH_URL} 에 응답하지 않습니다."
  exit 1
}

_ensure_model() {
  if lms ps 2>/dev/null | grep -qiE 'model|llm'; then
    return 0
  fi
  echo "모델 로드 시도: ${MODEL}"
  if lms load "${MODEL}" -y --gpu max --context-length "${CTX}" 2>/dev/null; then
    return 0
  fi
  # repo 이름 일부로 재시도
  local slug="${MODEL##*/}"
  slug="${slug%-GGUF}"
  slug="${slug##*/}"
  if [[ -n "$slug" ]] && lms load "${slug}" -y --gpu max --context-length "${CTX}" 2>/dev/null; then
    return 0
  fi
  echo "WARN: 자동 로드 실패. LM Studio에서 모델을 수동 로드하세요."
  echo "  다운로드: lms get \"${MODEL}\" --gguf -y"
  echo "  로드:     lms load \"${MODEL}\" --gpu max -c ${CTX}"
}

_ensure_server

if _is_healthy; then
  _ensure_model
  echo "LM Studio 서버 정상 실행 중"
  echo "  provider: lmstudio (GGUF)"
  echo "  model:    ${MODEL}"
  echo "  url:      http://127.0.0.1:${PORT}/v1"
  echo ""
  echo "  API model ID는 LM Studio Developer 탭 표시값과 일치해야 합니다."
  echo "  다를 경우 infra/.env 의 LLM_MODEL 을 해당 값으로 수정하세요."
  lms ps 2>/dev/null || true
fi
