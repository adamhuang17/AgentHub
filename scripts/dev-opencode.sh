#!/usr/bin/env bash
set -euo pipefail
echo "Compatibility alias. Prefer scripts/dev-agent-runtime.sh."
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dev-agent-runtime.sh"
