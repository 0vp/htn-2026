#!/usr/bin/env bash
set -euo pipefail
# Native image, CUDA Python runtime and model assets must already be provisioned.
test "$EUID" = 0
test -x /opt/htn/gpu-env/bin/python
test -d /opt/htn/models/XFeat
docker image inspect sha256:d724dfb15832629f33d3eb64ea1bb0b5453f786a7804125a6da5defe5c95c111 >/dev/null
id htn-map >/dev/null 2>&1 || useradd --system --gid htn --shell /usr/sbin/nologin htn-map
install -d -m 750 /etc/htn
if [[ ! -f /etc/htn/gpu.env ]]; then
  python3 - <<'PY'
import secrets
from pathlib import Path
p = Path('/etc/htn/gpu.env')
p.write_text('HTN_GPU_TOKEN=' + secrets.token_urlsafe(32) + '\n')
p.chmod(0o600)
PY
fi
chmod 2770 /var/lib/htn
find /var/lib/htn -maxdepth 1 -name 'rooms.sqlite3*' -exec chmod 660 {} +
install -m 755 /opt/htn/backend/deploy/processing/hydra-worker /opt/htn/hydra-worker
install -m 644 /opt/htn/backend/deploy/processing/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now htn-hydra htn-gpu htn-processing
