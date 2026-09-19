# Architecture research for 10,000 official TPS

Research date: 2026-09-19. Target is the ranked hidden-workload geometric mean,
including prefill, with every gate passing. The last supplied verified best is
571.446 TPS; reaching 10,000 would require 17.5x that score. This document is
research and analytical estimates, not measured GPU improvement.

## Where an order of magnitude would have to come from

Using the pinned configuration in `OPTIMIZATION_GUIDE.md`, matrix parameters are:

```
P = 36 * (2560*(4096+1024+1024) + 4096*2560 + 3*2560*9728)
    + 151936*2560
  = 4,022,272,000
```

This counts the tied embedding/LM head once; normalization parameters are tiny.
An ordinary full decode round reads about 8.0445 GB of BF16 matrices. Under
the optimistic streaming assumption that each weight is read once per round,
3.35 TB/s implies 2.401 ms and 416 rounds/s, before KV traffic, kernels or IPC.
It implies roughly 416/1,666/6,663 output TPS at B1/B4/B16. This is an estimate
for ordinary dense evaluation, not an impossibility theorem for all algorithms.
Cache retention and exact transformations can alter the traffic model.

The hardware inputs are NVIDIA's H100 SXM specifications: 3.35 TB/s and about
989 TFLOP/s dense BF16. Its displayed 1,979 BF16 figure includes sparsity;
that sparse throughput must not be used for this dense checkpoint.
[NVIDIA specifications](https://www.nvidia.com/en-us/data-center/h100/).

With perfect weight streaming, reaching 10,000 decode-only TPS would require
about 24/6/1.5 committed tokens per sequence per weight sweep at B1/B4/B16.
Real requirements are higher because verification increases computation and
prefill remains. Kernel fusion improves utilization but cannot by itself
deliver arbitrary reductions in required weight traffic.

Dense prefill matrix FLOPs, excluding the final head, are approximately
7.2666 GFLOP per input token. At the optimistic dense peak, ignoring attention
and all overhead, the conventional computation gives:

| Public B/S/O | Prefill matrix time | Output TPS if decode were free |
| --- | ---: | ---: |
| 1/512/32 | 3.76 ms | 8,506 |
| 4/2048/32 | 60.19 ms | 2,127 |
| 16/512/128 | 60.19 ms | 34,025 |

These are analytical ceilings under conventional dense prefill, not benchmark
predictions. Some final-layer prompt work can be eliminated when only the last
logit is needed, so they are not strict bounds for every exact implementation.
Private shapes are unknown: these public examples neither prove nor disprove
a 10,000 private geometric mean. They do show why a decode-only claim is
insufficient, especially for long prompts and short outputs.

## Exact proposals without auxiliary weights

**Lookahead/Jacobi is the strongest distinct algorithmic experiment.**
The authors generate candidate n-grams using parallel fixed-point iterations,
then verify candidates with the full target. Plain Jacobi iterations alone
often fail to improve wall time; Lookahead retains useful trajectories instead.
Their reported single-GPU gains are 1.5–2.3x on other models/workloads, not 17x
or a prediction for Qwen3. Its branch mask prevents unrelated candidate paths
from attending to one another.
[Author explanation](https://www.lmsys.org/blog/2023-11-21-lookahead-decoding/),
[paper](https://arxiv.org/abs/2402.02057).

The reference implementation is model-specific and documents LLaMA support;
its optional specialized FlashAttention extension is not usable as a new
compiled dependency in Dryft. Port the algorithm to the existing Qwen engine
and Python/Triton runtime, not its installation recipe.
[Author repository](https://github.com/hao-ai-lab/LookaheadDecoding).

**Tree verification is a reusable mechanism, not a proposal-quality solution.**
Several candidate suffixes can share the same prefix evaluation, with each node
attending only to committed context and its ancestors. SpecInfer supplies the
primary algorithmic reference. Its auxiliary speculative models and FlexFlow
runtime are not deployable dependencies here. Request-local suffix candidates
or Lookahead trajectories could feed our own verifier instead.
[SpecInfer paper](https://arxiv.org/abs/2305.09781),
[author artifact](https://github.com/goliaro/specinfer-ae).

**Layer-skipping drafting is a secondary experiment.** Draft & Verify reuses
the target weights with selected layers skipped only while proposing; every
committed token still needs complete target verification. The authors report
up to 1.99x on LLaMA-2 variants. That establishes a research avenue, not a
working skip pattern for Qwen3 or permission to approximate final output.
Its draft cache must be separate from the full-model committed cache.
[Paper](https://arxiv.org/abs/2309.08168),
[author code](https://github.com/dilab-zju/self-speculative-decoding).

Our existing suffix variants used a native verifier and did not improve the
official score. This does not measure a graphed fused verifier, but also gives
no evidence that suffix acceptance is adequate. Instrument acceptance before
building a large tree. Do not count a more sophisticated lookup data structure
as a gain without increased useful acceptance or reduced measured overhead.

## Concrete implementation priorities

1. **Measure the winning engine's verification cost curve.** For the same
   public shapes, record GPU decode time and exact causal verification time
   for widths 1/2/4/8, plus acceptance, cache-commit time, prefill and host time.
   The decision condition is `E[committed] > (draft + verify + commit)/decode`.
   Compare against graph_fused, not the slower untouched starter.
2. **Build reusable fixed-width graph verification.** Reuse packed projections,
   BF16 norm/SwiGLU fusion and native prefill. Graphs for a few bounded widths
   need stable token/position/mask buffers. One-token folded attention cannot
   simply be reused: verification positions have different causal histories.
   Start with linear suffix proposals to isolate verifier overhead.
3. **Add a small Lookahead branch and request-local trajectory pool.** Initial
   experiment: bounded lookahead window and 3- or 4-token candidate chains;
   jointly evaluate independent branches with explicit block/ancestor masks.
   Keep the already-produced first token fast. Measure whether accepted tokens
   compensate for the extra full-vocabulary head and attention work.
4. **Remove the batch-wide minimum-acceptance bottleneck.** Current batched
   speculation discards every row's extra accepted tokens when one row misses.
   Use per-row committed lengths and bounded output FIFOs, with row-specific
   positions and initialized-slot masks. The public stream still emits one
   token per row each step. Refill rows only when necessary; measure wasted
   masked work and the slowest row's effect before investing in a scheduler.
5. **Try branching suffix verification only if competing candidates exist.**
   Nodes require depth-derived RoPE positions, ancestor masks, and selected
   path KV compaction across all 36 layers. Token-tree layouts must not treat
   sibling tokens as temporal predecessors. Reject all nonselected KV state.
6. **Evaluate layer-skipping drafting after verifier infrastructure exists.**
   Avoid large searches inside the 300-second loading budget. Use fixed
   documented patterns as experiments, full target verification, and disable
   drafting promptly when acceptance cannot repay the work.

For independent rows with per-token acceptance probability p, requiring all B
rows to accept a draft position gives p^B under a simplifying independence
model. At p=0.8 and B=16 this is only 0.028. This is a diagnostic illustration,
not a measured probability; it explains why lockstep speculation can erase
gains even when individual rows have reasonable acceptance.

All candidates must reset trajectories, lookup structures, FIFOs and positions
per generate; preserve BF16 boundaries; emit exactly the requested step count;
and validate logits, cached steps and consecutive different prompts. Do not
reuse prompt-dependent data across requests. Retain failed runs and compare
matching specification digests. A successful small local logic test is not
evidence for GPU correctness, speed, graph safety or the 10,000-TPS goal.

## Research conclusion

There is no primary-source evidence here that a drop-in, source-only method
achieves the requested 17.5x gain under these constraints. The plausible path
combines a much faster exact verifier, useful parallel candidate generation,
independent row progress, and prefill improvements. Each has a falsifiable
benchmark; none should be presented as a guaranteed route to 10,000 TPS.

## Fable 5.1 cross-review

The local CLI completed a second architecture review, retained in ignored
`results/claude-fable-tenk.json`. It independently prioritized bandwidth
attribution and multi-token verification, but several conclusions are rejected:

- Its public-shape geometric mean is not the official hidden-shape score.
  Its suggested 1,500-2,500 replacement target is unsupported and does not
  supersede the user's 10,000 objective.
- The checker uses the emitted token's deficit from the teacher-forced argmax,
  with documented margin 2.0, not an unknown top-1/top-2 threshold.
- Its assertion that extra verification rows are effectively free is an
  unmeasured hypothesis. Attention, vocabulary projection and GEMM costs grow.
- Matching BF16 cast boundaries does not prove a split-K reduction equivalent;
  numerical validation remains necessary. Prefer deterministic staged reduction
  over floating-point atomics for a controlled experiment.
- Prompt IDs come from a corpus according to the contract; random synthetic
  tokens are a robustness test, not evidence of the hidden distribution.

Retain the useful proposals while measuring their costs and acceptance against
the actual fused winner. Do not adopt an inferred ceiling as a proven limit.

## First implementation candidate

`graph_verify` adds a reusable `GraphVerifier` with captured input widths
1/2/3/4, using the fused winner's operations and native dynamic prefill. It
verifies adaptive request-local suffix proposals, computes predictions at every
verification position, and retains the batch's common accepted prefix plus the
correction token. Logical cache rollback hides rejected slots; every subsequently
visible slot is overwritten before attention. This first experiment intentionally
isolates verifier overhead before adding new proposal algorithms or per-row progress.

CPU orchestration tests cover exact output count, accepted-prefix generation,
batch output, and consecutive requests. Packaging and tooling checks pass.
CUDA capture, numerical correctness, warmup cost and performance are unverified
until the official candidate runs. Four graph widths can increase warmup time
and memory; neither is assumed free. It is queued after residual fusion and norm
warp tuning. The active pending residual submission is unchanged remotely.
