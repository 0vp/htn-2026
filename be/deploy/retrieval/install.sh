#!/usr/bin/env bash
set -euo pipefail
# Existing host CUDA Torch is reused; retrieval-specific dependencies are isolated.
test "$EUID" = 0
source_dir=$(cd "$(dirname "$0")/../.." && pwd)
/usr/bin/python3.10 -c 'import torch; assert torch.__version__ == "2.9.1+cu129"'
install -d -o q -g htn -m 2770 /var/lib/htn-models
if [[ ! -x /opt/htn/retrieval-env/bin/python ]]; then
  uv venv --python /usr/bin/python3.10 --system-site-packages /opt/htn/retrieval-env
fi
uv pip install --python /opt/htn/retrieval-env/bin/python \
  -r "$source_dir/deploy/retrieval/requirements.txt"
install -m 644 "$source_dir/deploy/retrieval/htn-retrieval.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now htn-retrieval
