#!/usr/bin/env bash
set -euo pipefail
# Provision the isolated evaluation worker; does not change running services.
source_dir=$(cd "$(dirname "$0")/../.." && pwd)
root=/opt/htn/esam
sudo mkdir -p "$root"
sudo chown "$(id -u):$(id -g)" "$root"
sudo apt-get install -y libopenblas-dev libegl1 python3.10-dev python3-tk gcc-11 g++-11
cd "$root"
if [[ ! -x env/bin/python ]]; then
  uv venv --python /usr/bin/python3.10 env
fi
uv pip install --python env/bin/python torch==2.1.0 torchvision==0.16.0 \
  --index-url https://download.pytorch.org/whl/cu118 --no-cache
uv pip install --python env/bin/python -r "$source_dir/deploy/esam/requirements.txt" \
  -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.1/index.html --no-cache
uv pip install --python env/bin/python torch-scatter==2.1.2+pt21cu118 \
  -f https://data.pyg.org/whl/torch-2.1.0+cu118.html --no-cache
if [[ ! -x bin/micromamba ]]; then
  curl -fLs https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj bin/micromamba
fi
if [[ ! -x cuda/bin/nvcc ]]; then
  MAMBA_ROOT_PREFIX="$root/mamba" bin/micromamba create -y -p "$root/cuda" \
    -c nvidia/label/cuda-11.8.0 cuda-nvcc cuda-cudart-dev cuda-libraries-dev
  MAMBA_ROOT_PREFIX="$root/mamba" bin/micromamba clean --all -y
fi
env/bin/python - "$source_dir/deploy/esam/models.json" <<'PY'
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

models = json.loads(Path(sys.argv[1]).read_text())
for name, metadata in models.items():
    directory = "upstream" if name == "esam" else name
    if not Path(directory).exists():
        subprocess.run(["git", "clone", metadata["source"], directory], check=True)
    subprocess.run(["git", "-C", directory, "checkout", metadata["revision"]], check=True)
    if "checkpoint" not in metadata:
        continue
    Path("weights").mkdir(exist_ok=True)
    filename = "ESAM-E_online_epoch_128.pth" if name == "esam" else "FastSAM-x.pt"
    path = Path("weights") / filename
    if not path.exists():
        temporary = path.with_suffix(".download")
        urllib.request.urlretrieve(metadata["checkpoint"], temporary)
        temporary.replace(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != metadata["sha256"]:
        raise RuntimeError(f"Checkpoint checksum mismatch: {name}")
PY
export CUDA_HOME="$root/cuda"
export PATH="$root/env/bin:$PATH"
export CPLUS_INCLUDE_PATH="$root/nvtx/c/include"
export CC=gcc-11 CXX=g++-11 MAX_JOBS=2 TORCH_CUDA_ARCH_LIST=8.9 OMP_NUM_THREADS=2
(cd minkowski && "$root/env/bin/python" setup.py install --force_cuda --blas=openblas)
(cd upstream/thirdparty/pointops && "$root/env/bin/python" setup.py install)
mkdir -p backend/src
rsync -a --exclude __pycache__ "$source_dir/src/" backend/src/
sudo install -m 755 "$source_dir/deploy/esam/esam-worker" /opt/htn/esam-worker
PYTHONPATH="$root/upstream:$root/fastsam" env/bin/python -c \
  'import torch, MinkowskiEngine, pointops, oneformer3d; assert torch.cuda.is_available()'
