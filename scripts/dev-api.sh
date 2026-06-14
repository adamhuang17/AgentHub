#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f .env ]; then set -a; source .env; set +a; fi
export PORT="${PORT:-8000}"
export AGENTHUB_DB_PATH="${AGENTHUB_DB_PATH:-var/agenthub.sqlite3}"
export AGENTHUB_ARTIFACT_STORE_DIR="${AGENTHUB_ARTIFACT_STORE_DIR:-var/artifacts}"
export AGENTHUB_STATIC_DEPLOY_DIR="${AGENTHUB_STATIC_DEPLOY_DIR:-var/static-deployments}"
echo "starting_agenthub_api http://127.0.0.1:${PORT}"
python -B -m services.api.app.main
