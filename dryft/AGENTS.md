# Workspace conventions

- Use uv for all Python installation, dependency management, and execution. Do not use pip, Conda, or bare system Python for this project.
- Python is pinned in `.python-version` and `pyproject.toml`; uv is pinned by `tool.uv.required-version`. Preserve these pins unless deliberately updating them.
- Use `uv sync --locked` and `uv run --locked ...`. For Linux x86_64 GPU development, use `uv sync --locked --extra gpu` and `uv run --locked --extra gpu ...`.
- Pin direct dependencies exactly and regenerate `uv.lock` with `uv lock` after an intentional dependency change. Keep the lockfile with the project to pin transitive dependencies and artifact hashes.
- Windows is for preparation tooling. The Linux-only GPU extra targets the published CUDA 12.4 runtime; Windows does not install that extra's packages.
- Do not create a nested Git repository in dryft. The Git repository is the parent `htn-2026` folder. The user subsequently authorized committing and pushing immediately, superseding the earlier 00:08 schedule. Exclude ignored environments, binaries, credentials, logs, and results. Preserve existing parent history.
- Keep the official starter unchanged until it is available and its instructions have been read. Do not invent a replacement engine.
- The official starter has been imported at revision `c2405f19fae577539969c5face3914b116757ae6`. Read `QWEN_ENGINE_CONTRACT.md` before engine edits and `OPTIMIZATION_GUIDE.md` before replacing model operations. Upstream agent guidance is preserved in `docs/starter/AGENTS.md`; the uv conventions here take precedence over upstream pip examples.
- Only `dryft/engine` relative to the parent repository is the submission folder. Keep agents, notes, tokens, and tools outside it. Consult live website/CLI behavior when old starter public-run instructions conflict with the current participant guide.

## Optimization constraints and validation

- Preserve the pinned model's formulas and BF16 rounding boundaries. RMSNorm reduces and normalizes in FP32, casts normalized values to the input dtype, then multiplies the learned weight.
- Q and K receive per-head RMSNorm before RoPE; V does not. Preserve absolute positions, RoPE theta 5,000,000, attention scale 1/sqrt(128), and GQA mapping `kv_head = query_head // 4`.
- Preserve tied embedding/LM-head weights, bias-free projections, SwiGLU, and both residual branches. Hidden width 2560 differs from the 4096-wide query projection.
- Reset all prompt-dependent cache state and positions before every `generate`, including after warmup. Never attend to unused cache capacity.
- `attention_mask=None` is only safe in the guide's full unpadded prefill into an empty dynamic cache followed by single-token decode. Static caches, chunked prefill, and multi-token verification need correct causal and initialized-slot masks.
- CUDA graph capture requires stable buffer addresses and in-place token/position updates. Keep `.tolist()` and `yield` outside capture. Compile specializations and prepare shape-dependent buffers during warmup within the load/warmup budget.
- Yield one host list per output step, exactly `max_new_tokens` times, with one token per sequence; EOS must not stop generation. Computing all tokens before the first yield can fail TTFT.
- Start with isolated leaf-operation replacements, then evaluate reduced wrapper dispatch, static cache, and graphed decode. Full-block or persistent megakernels require evidence and correct cross-block synchronization; guide examples do not guarantee speedups.
- Before promoting a change, compare untouched baseline prefill logits, several cached decode steps, and consecutive generation calls with different prompts. Cover all public shapes and avoid hardcoding hidden workload assumptions.
- Judge correctness, TTFT, TPOT, throughput including prefill, memory, and timing stability together. Local archive checks are not GPU correctness/performance tests. Retain failures and compare matching benchmark specification digests.
- Source-only Python/Triton must work with PyTorch 2.5.1, Triton 3.1.0 and Transformers 4.51.3. Newer library examples require explicit compatibility checks. Quantization and approximate attention/cache pruning are prohibited.
