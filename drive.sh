#!/bin/sh
# Arrow-key driving + agent/iOS WebSocket. Usage: sh drive.sh [drive.py options]
#   sh drive.sh                                  keyboard + ws://127.0.0.1:8793
#   sh drive.sh --host 0.0.0.0 --token SECRET    also reachable from a phone on the LAN
cd "$(dirname "$0")/robot/scripts" || exit 1
PORT=${ROBOT_PORT:-$(ls /dev/cu.usbserial-* 2>/dev/null | head -1)}
[ -n "$PORT" ] || { echo "No /dev/cu.usbserial-* found: plug in the ESP32 TTL port"; exit 1; }
echo "Using $PORT"
exec ../../be/.venv/bin/python drive.py "$PORT" "$@"
