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

## Static graph result and next decision

Run `dc47faa4-524c-42a5-b226-5eb207546ab2` passed all public correctness checks
but failed the overall latency gate; it has no ranked official score.

| Public shape | Candidate/native TTFT ms | Candidate/native TPOT ms |
| --- | --- | --- |
| B1 S512 O32 | 22.75 / 22.42 | 9.25 / 18.99 |
| B4 S2048 O32 | 261.74 / 201.75 | 17.29 / 20.86 |
| B16 S512 O128 | 209.51 / 191.86 | 18.74 / 22.78 |

B1 decode improved substantially. B4 first-token latency exceeded the 1.10x
gate (1.297x). Native dynamic prefill followed by graph decode is therefore the
next experiment, already implemented as graph_hybrid. Graph_folded then tests
avoiding KV repetition; graph_norms tests fusion. These measurements do not
uniquely identify a kernel bottleneck and do not establish the 2000 TPS goal.
The actual results have been sent to Fable for the next research iteration.

## Ranked graph improvements

- Native-prefill graph: **286.813834 official TPS**, all gates passed, run
  `3277a3b4-5f4c-4759-aa15-3b140329cad2`.
- Combined graph_fused: **571.446130 official TPS**, all gates passed, run
  `727ff60a-59a2-4e44-b44f-d7f63fd7427c`, commit `da6004c`.

graph_fused combines native prefill, folded GQA decode, packed QKV/gate-up,
all RMSNorm replacements and fused SwiGLU. Public B1/B4/B16 TPOT was
6.396 / 9.213 / 7.063 ms; paired native ratios were 0.287 / 0.389 / 0.297.
Public B16 throughput reached 1956.80 TPS, but that is NOT the official score
and does not achieve the 2000 official TPS goal. Peak run memory was 26.89 GB.

The next incremental graph_residual candidate retains that configuration and
fuses the post-attention residual addition with RMSNorm. The residual sum is
rounded to BF16 before the FP32 variance, and normalized values are rounded
again before multiplying the learned weight. Local archive/tooling checks
passed; its GPU correctness and performance remain pending.

Folded attention with native prefill, without the other fusions, passed at
**412.6689999 official TPS**, run `bb32171a-a5da-40f4-86fb-4eeb31493e75`.
Public B1/B4/B16 TPOT was 9.274 / 12.030 / 10.280 ms, with paired native
ratios 0.332 / 0.394 / 0.362. The combined graph_fused remains the winner.
A frontend-only push triggered another run of the identical engine tree;
that duplicate was canceled before resuming the residual-fusion candidate.

Residual fusion passed at **561.297972 official TPS**, run
`e7fe5b33-d9c7-47f3-be06-387564860630`, commit `ae5780d`.
Public B1/B4/B16 TPOT: 6.516 / 9.369 / 7.245 ms; paired native ratios
0.264 / 0.357 / 0.289. Raw score is 1.78% below graph_fused; paired reference
timings differ, so this is not proof of a stable regression or improvement.
Keep graph_fused as the measured best. Next: norm launch tuning and graph_verify.
