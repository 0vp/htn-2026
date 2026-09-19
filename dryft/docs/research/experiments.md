# Sequential optimization experiments

Run `uv run --locked scripts/experiments.py` from dryft to run or resume the
official sweep. Use `--status` to inspect its saved state. The connected main
branch is the submission mechanism, so each candidate requires a Git push.
The runner preserves other work and stops on a dirty checkout or diverged history.

Each candidate uses independent immutable options in `engine/options.py`.
Reusable operations live in `engine/kernels`; model adapters, execution, and
exact proposal verification live in `engine/components`. `combined` tests
interactions after individual candidates. Nothing is promoted solely on local
archive validation: official correctness, latency and ranking must pass.

The control is run `4eec26fe-79bb-4af7-ad78-b4b28355a154`: 204.779793 tokens/sec,
ranked and successful. Its specification digest starts `b103e41b`.
Only matching specification digests are comparable. Failed runs are retained.
Raw logs, results and restart state remain ignored under `results/`.

Order: hidden norms, all norms, direct forward, native GQA, static cache,
CUDA graph decode, SwiGLU, packed projections, LM-head GEMV, custom decode
attention, exact prompt-lookup speculation, then a combined configuration.
Static cache includes direct forward; graph includes static cache. Compare
those incremental steps as well as comparing each candidate to the control.

The winner must beat the control and pass a final official confirmation.
Whole-model persistent megakernels are not implemented by this sweep; they
require a separate synchronization design and cannot be claimed tested here.

Windows tests validate runner behavior and packaging. Model equivalence and
performance require the official H100 runtime. Candidates run an additional
small prefill/cached-step/consecutive-call token regression during model load.
This diagnostic is stricter than the official logit tolerance; a diagnostic
failure is not evidence that the method can never satisfy the official rule.
