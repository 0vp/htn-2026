#!/bin/sh
# Codex worker on this laptop: runs the phone's voice commands through your local `codex login`.
# Start `sh drive.sh` first so the agent can move the base. Usage: sh agent.sh [--no-motion]
cd "$(dirname "$0")/be" || exit 1
exec .venv/bin/python -m htn_backend.agent.worker "$@"
