#!/bin/sh
# One launcher for the robot: arrow-key driving, the cloud link, and the local Codex agent.
#   sh drive.sh                 everything (Codex log opens in a second Terminal window)
#   sh drive.sh --no-agent      keyboard/app driving only
#   other options pass through to robot/scripts/drive.py (e.g. --speed 0.3, --no-cloud)
ROOT=$(cd "$(dirname "$0")" && pwd)
PORT=${ROBOT_PORT:-$(ls /dev/cu.usbserial-* 2>/dev/null | head -1)}
[ -n "$PORT" ] || { echo "No /dev/cu.usbserial-* found: plug in the ESP32 TTL port"; exit 1; }

AGENT=1
for arg in "$@"; do [ "$arg" = "--no-agent" ] && AGENT=0; done
if [ "$AGENT" = 1 ]; then
  LOG="$ROOT/robot/agent.log"
  : > "$LOG"
  # The worker waits for drive.py's local WebSocket on its own; Codex runs with your `codex login`.
  (cd "$ROOT/be" && exec .venv/bin/python -m htn_backend.agent.worker >> "$LOG" 2>&1) &
  WORKER=$!
  trap 'kill $WORKER 2>/dev/null' EXIT INT TERM
  osascript -e "tell application \"Terminal\" to do script \"clear; echo 'Codex agent (local)'; tail -f '$LOG'\"" >/dev/null 2>&1 \
    || echo "Codex log: tail -f $LOG"
fi

echo "Using $PORT"
cd "$ROOT/robot/scripts" || exit 1
ARGS=$(for arg in "$@"; do [ "$arg" = "--no-agent" ] || printf '%s\n' "$arg"; done)
# shellcheck disable=SC2086
../../be/.venv/bin/python drive.py "$PORT" $ARGS
