#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
if [[ -x "$root/agent/codex/codex-rs/target/release/codex" ]]; then
  export CODEX_BINARY="$root/agent/codex/codex-rs/target/release/codex"
fi
exec uv run --project "$root/be" python -m htn_backend.agent.run "$@"
