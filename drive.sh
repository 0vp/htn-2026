#!/bin/sh
# One launcher for the robot: arrow-key driving, the cloud link, and the local Codex agent.
#   sh drive.sh                 everything (Codex log opens in a second Terminal window)
#   sh drive.sh --no-agent      keyboard/app driving only
#   sh drive.sh --restart-agent restart the Codex agent too (needed after agent code changes)
#   sh drive.sh --badge         drive from the badge over its USB cable (auto-detects the port)
#   other options pass through to robot/scripts/drive.py (e.g. --speed 0.3, --no-cloud)
ROOT=$(cd "$(dirname "$0")" && pwd)
PORT=${ROBOT_PORT:-$(ls /dev/cu.usbserial-* 2>/dev/null | head -1)}
[ -n "$PORT" ] || { echo "No /dev/cu.usbserial-* found: plug in the ESP32 TTL port"; exit 1; }

AGENT=1
RESTART=0
BADGE=0
for arg in "$@"; do
  [ "$arg" = "--no-agent" ] && AGENT=0
  [ "$arg" = "--restart-agent" ] && RESTART=1
  [ "$arg" = "--badge" ] && BADGE=1
done
# The badge is the ESP32-C3's native USB port (usbmodem), never the base's TTL port (usbserial).
if [ "$BADGE" = 1 ]; then
  BADGE_PORT=${BADGE_PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}
  [ -n "$BADGE_PORT" ] || { echo "No /dev/cu.usbmodem* found: plug in the badge"; exit 1; }
  echo "Badge on $BADGE_PORT (close 'pio device monitor' if it is open)"
fi
if [ "$AGENT" = 1 ]; then
  LOG="$ROOT/robot/agent.log"
  # One Codex agent and one log window, reused across restarts of this script. The agent keeps
  # its memory; pass --restart-agent after changing agent code.
  [ "$RESTART" = 1 ] && pkill -f "htn_backend.agent.worker" 2>/dev/null && sleep 1
  if pgrep -f "htn_backend.agent.worker" >/dev/null; then
    echo "Codex agent already running: reusing it"
  else
    (cd "$ROOT/be" && exec nohup .venv/bin/python -m htn_backend.agent.worker >> "$LOG" 2>&1) &
  fi
  if ! pgrep -f "tail -f $LOG" >/dev/null; then
    # Show Codex live in its own window: Ghostty when installed, else Terminal.
    if [ -d /Applications/Ghostty.app ]; then
      open -na Ghostty --args --title="Codex agent" -e sh -c "echo 'Codex agent (local)'; tail -f '$LOG'" >/dev/null 2>&1
    else
      osascript -e "tell application \"Terminal\" to do script \"clear; echo 'Codex agent (local)'; tail -f '$LOG'\"" >/dev/null 2>&1
    fi || echo "Codex log: tail -f $LOG"
  fi
fi

echo "Using $PORT"
cd "$ROOT/robot/scripts" || exit 1
ARGS=$(for arg in "$@"; do
  if [ "$arg" = "--no-agent" ] || [ "$arg" = "--restart-agent" ]; then
    continue
  elif [ "$arg" = "--badge" ]; then
    printf '%s\n%s\n' --badge "$BADGE_PORT"
  else
    printf '%s\n' "$arg"
  fi
done)
# shellcheck disable=SC2086
../../be/.venv/bin/python drive.py "$PORT" $ARGS
