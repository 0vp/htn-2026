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

## Completed measurements (2026-09-19)

All rows below have the same specification digest and passed the official gates.
Native latency ratios are paired within each run; scores are absolute and can
move with device conditions. Public ratios do not establish hidden-case gains.

| Candidate | Official TPS | Public B1/B4/B16 TPOT ratio to native |
| --- | ---: | --- |
| Original control | 204.78 | 0.987 / 0.997 / 0.984 |
| Hidden norms | 177.44 | 0.967 / 1.006 / 0.954 |
| All norms | 204.19 | 0.778 / 0.802 / 0.806 |
| Fixed prompt lookup | 162.70 | 0.942 / 0.965 / 0.975 |
| Adaptive suffix B1 | 175.14 | 0.962 / 1.005 / 0.940 |

All norms is promising despite the raw score: paired public TTFT and TPOT fell
roughly 19–22%. Fixed lookup has only a modest paired B1 improvement; B4/B16
use unchanged native generation in that mode, so their small differences are
not evidence of speculative benefit. Repeat promising results before promotion.

Run IDs, in table order:
- `4eec26fe-79bb-4af7-ad78-b4b28355a154`
- `29982948-7867-4755-86b4-bff693558d56`
- `0fd39406-8e8a-45bf-8178-723f8fa4e961`
- `59f7355e-6d4b-4505-b6da-a4d68e14c715`
- `58218a38-14d3-431b-83bf-657836c93745`

Run `uv run --locked scripts/analyze.py` for the current paired measurements.
The batched adaptive suffix and graph combinations remain pending. The active
goal is 2000 official TPS, not completion of this initial sweep.

After the B1 adaptive suffix result, graph experiments were moved immediately
after the already-submitted batched suffix run. The modest 4% paired B1 TPOT
gain from adaptive suffix does not yet justify further speculation tuning.
Graph-only, native-prefill graph, folded-head graph, and norms-plus-graph will
test larger dispatch and KV-copy reductions before the remaining leaf variants.
Every originally listed candidate remains in the sequential sweep.
