#!/usr/bin/env bash
set -euo pipefail
# Run as root after placing the backend in /opt/htn/backend and Python in /opt/htn/python.
if [[ "$EUID" != 0 ]]; then
  echo 'Run as root.' >&2
  exit 1
fi
id htn >/dev/null 2>&1 || useradd --system --home /var/lib/htn --shell /usr/sbin/nologin htn
UV_PROJECT_ENVIRONMENT=/opt/htn/venv uv sync \
  --project /opt/htn/backend --locked --no-dev --python /opt/htn/python/bin/python3.11
install -m 644 /opt/htn/backend/deploy/htn-backend.service /etc/systemd/system/htn-backend.service
systemctl daemon-reload
systemctl enable --now htn-backend
systemctl restart htn-backend
