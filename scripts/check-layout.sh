#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
required=(
  "services/api/app/main.py"
  "apps/web/package.json"
  "apps/web/packages/app/src/pages/agenthub.tsx"
  "apps/web/packages/app/src/agenthub/api/agenthub-client.ts"
  "apps/web/packages/opencode/package.json"
  "docs/no-fake-success-policy.md"
)
failed=0
for path in "${required[@]}"; do
  if [ -e "$ROOT/$path" ]; then echo "ok $path"; else echo "missing $path"; failed=1; fi
done
command -v python >/dev/null || { echo "missing python"; failed=1; }
command -v bun >/dev/null || echo "bun_not_installed"
[ "$failed" -eq 0 ] || exit 1
echo "layout_ready"
