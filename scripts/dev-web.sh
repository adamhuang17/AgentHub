#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v bun >/dev/null || { echo "bun_not_installed"; exit 1; }
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
export VITE_AGENTHUB_API_BASE="${VITE_AGENTHUB_API_BASE:-${AGENTHUB_API_BASE_URL:-http://127.0.0.1:8000}}"
cd "$ROOT/apps/web"
echo "starting_agenthub_web /agenthub"
echo "VITE_AGENTHUB_API_BASE=$VITE_AGENTHUB_API_BASE"
bun --cwd packages/app dev
