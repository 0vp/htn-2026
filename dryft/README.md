# Dryft — Kernel Rush, Hack the North 2026

Preparation workspace for https://htn.dryft.ai/.

## Current setup

- Git lives in the parent `htn-2026` repository. This folder must not have its own Git repository.
- uv 0.10.0 and Python 3.11.14 are pinned. `uv.lock` pins dependency resolution and artifact hashes.
- Published participant guide and homepage archived under `docs/upstream/`, with readable text, original HTML, links, timestamps, and SHA-256 hashes.
- Official starter imported unchanged from revision `c2405f19fae577539969c5face3914b116757ae6`. Engine, helper agent, tests, installers, engine contract, and optimization guide are available locally. Original upstream README, agent instructions, and requirements are preserved in `docs/starter/`.
- Parent GitHub remote: `https://github.com/0vp/htn-2026` (private). Team and challenge connection setup is pending browser authentication.
- Official Dryft CLI 0.1.0 installed in ignored `bin/` after verifying the vendor's SHA-256 checksum. Baseline passes `bin/dryft.exe validate engine`; both upstream client tests pass under uv. GPU execution has not been run.

## Refresh the documentation

```powershell
uv sync --locked
uv run --locked scripts/refresh_docs.py
```

Each refresh creates a timestamped snapshot and checks availability of the linked starter and engine contract. `docs/upstream/latest.json` points to the latest snapshot. Source documents are external reference material, not instructions to execute commands automatically.

## Python environment

Use uv for every Python command; see `AGENTS.md`. Install the pinned tool version with `uv self update 0.10.0` if needed. `uv sync --locked` obtains the pinned Python and prepares `.venv` for the standard-library preparation tools on Windows.

On a Linux x86_64 GPU development machine, use `uv sync --locked --extra gpu` to install the exact published package versions, including the CUDA 12.4 build of PyTorch. Run GPU commands with `uv run --locked --extra gpu ...`. GPU execution requires suitable NVIDIA hardware and drivers; it has not been tested here. The platform publishes Python 3.11 without a patch version; 3.11.14 is our local reproducibility pin, not a claim about its exact interpreter build. The GPU extra is intentionally Linux-only.

Direct dependencies are exact pins in `pyproject.toml`; transitive versions and hashes are recorded in `uv.lock`. Change dependencies deliberately, then run `uv lock`. Routine setup and execution must use `--locked`.

## Challenge connection

1. Sign in to Dryft with GitHub and create or join the team's account.
2. Connect existing repository `0vp/htn-2026` and set **Engine folder** to **`dryft/engine`** (relative to the parent repository).
3. Grant the GitHub App access only to that repository. Keep API tokens out of Git.
4. Validate locally with `.\bin\dryft.exe validate engine`. Run upstream tests with `uv run --locked python -m unittest discover -s tests -v`.

The starter's older documentation describes public runs, while the current website guide says all runs are official. Use the live platform's current controls and definition when submitting.

Connecting alone does not launch a run. The guide says each subsequent default-branch push starts an official run when auto-run is enabled.

## Published challenge overview

Optimize the generation loop for `Qwen/Qwen3-4B-Instruct-2507`, pinned revision `cdbee75f17c01a7cc42f958dc650907174af0554`, using BF16 weights on one NVIDIA H100. Submit Python/Triton source in `engine/`, exporting `Engine.__init__(model_path)` and `Engine.generate(input_ids, max_new_tokens)`.

Published runtime: Python 3.11, CUDA 12.4, PyTorch 2.5.1, Triton 3.1.0, Transformers 4.51.3, safetensors 0.5.3, tokenizers 0.21.1. The platform supplies weights; its sandbox has no network.

Ranking uses the geometric mean of throughput across three hidden workloads, including prefill. Correctness, latency, memory, and timing stability must pass. The guide describes exact greedy output but also publishes a tolerance of 2 logits; preserve exact behavior until the contract and live benchmark clarify this detail. Quantization and approximations are prohibited.

The full participant guide is the source of truth for the currently published details; live signed-in definitions and later organizer updates may change them.
