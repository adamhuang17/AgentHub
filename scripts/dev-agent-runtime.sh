#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v bun >/dev/null || { echo "bun_not_installed"; exit 1; }
cd "$ROOT/apps/web"
echo "starting_agenthub_coding_runtime http://127.0.0.1:4096"
bun run --cwd packages/opencode --conditions=browser src/index.ts serve --hostname 127.0.0.1 --port 4096 --cors http://127.0.0.1:3000 --cors http://localhost:3000
