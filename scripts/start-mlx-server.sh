#!/usr/bin/env bash
# 레거시 alias → LM Studio 서버 스크립트
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "NOTE: mlx_lm.server 대신 LM Studio(lmstudio-community GGUF)를 사용합니다."
exec "${ROOT}/scripts/start-lmstudio-server.sh"
