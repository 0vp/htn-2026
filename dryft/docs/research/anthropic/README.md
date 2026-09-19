# Anthropic / Paradigm kernel challenge: lessons for Dryft

Researched 2026-09-19. Research only: no external solution was executed,
submitted, copied into our engine, or independently benchmarked.

## What the challenge actually measures

This is a **Python simulator of a single-core VLIW SIMD processor**, not an
H100/CUDA/Triton benchmark. Python constructs instructions; the simulator runs
an integer tree traversal/hash computation. Its eight-wide vectors share
12 scalar ALU, six vector ALU, two load, two store and one flow slots per cycle;
scratch capacity is 1,536 32-bit words. Writes become visible after a cycle.
These constraints explain the emphasis on instruction scheduling and avoiding
gathers. [Upstream machine definition](https://github.com/anthropics/original_performance_takehome/blob/main/problem.py)

The current Paradigm judge uses forest height 10, 16 rounds, batch 256 and nine
fresh seeds. It scores the **worst cycle count**, lower is better. Output values
are required; output indices are optional. Submit the full `perf_takehome.py`
(maximum 1,000 KB), at most once per minute per X account. The server retains
the ten fastest distinct successful programs. Generation and trusted simulation
are separate sandbox phases; harness exploits are rejected. This is an
independent community board, migrated from kerneloptimization.fun, not an
Anthropic-run competition. Its model rows are individual reference runs, not
guaranteed reproducible model capability measurements.
[Current rules](https://www.paradigm.xyz/puzzles/anthropic-challenge/about)

The live public API showed **869 cycles, @HaydenCc51623, rank 1** when checked;
@SaifAlHarthi had 870 and @YuleHou 872. These are verified board entries, but I
did not establish public source repositories for those leading submissions.
[Leaderboard](https://www.paradigm.xyz/puzzles/anthropic-challenge),
[public leaderboard JSON](https://www.paradigm.xyz/puzzles/api/v1/vliw/leaderboard).
The old site's search snippets describe older cooldowns; use current rules.

## Public repositories and strength of evidence

| Repository | Available evidence | How to use it |
|---|---|---|
| [0xquinto/vliw-kernel-optimization](https://github.com/0xquinto/vliw-kernel-optimization) | Actual solution code, experiment history and a **self-reported 1,285 cycles**. No independently linked board placement established. | Best detailed optimization journal found. |
| [ericauld/anthropic-takehome-1199](https://github.com/ericauld/anthropic-takehome-1199) | Actual modified kernel builder on `takehome-1199`; repository name implies 1,199, but no independent result established. | Another inspectable scheduler implementation; do not treat the name as verification. |
| [amadeobonde/anthropic-kernel-challenge](https://github.com/amadeobonde/anthropic-kernel-challenge) | README and leaderboard image, **no solution source**. Live board independently confirms matching handle @amadeobonde at **1,358 cycles, rank 274** on research date. | Verified placement plus high-level account, not a reproducible implementation. |
| [Neuronspeeed/Anthropic-Original-Performance-Take-Home-Challenge](https://github.com/Neuronspeeed/Anthropic-Original-Performance-Take-Home-Challenge) | Self-reported **1,361 cycles**, approach description; current root listing lacks `perf_takehome.py`. | Write-up only; no independent verification. |

I opened actual kernel source in the first two repositories, not just their
READMEs. The first contains explicit read/write dependency tracking, critical
path priorities, resource-aware list scheduling and randomized scheduling trials.
The second exposes scratch-hazard handling, scheduling, vector hash generation
and cached shallow tree levels.
[Quinto inspected revision](https://github.com/0xquinto/vliw-kernel-optimization/blob/c3b7791f5f49f21a4ce255fd2c80f1b9f3e8d1f5/perf_takehome.py),
[Auld inspected revision](https://github.com/ericauld/anthropic-takehome-1199/blob/5172fbce2cf0f1fb758112b8992bafbc6a9d1b69/perf_takehome.py).

Quinto's journal reports vectorization, overlapping independent groups, caching
shallow tree nodes, shifting work away from saturated execution units, reducing
dependency chains and randomized scheduler search. It also records failed ideas:
moving too much work onto the flow engine and excessive scalar expansion hurt.
Its claimed 1,202-cycle lower bound is **for that implementation's operation
counts**, not a universal challenge limit; the current board is already below it.
[Experiment journal and rejected hypotheses](https://github.com/0xquinto/vliw-kernel-optimization/blob/main/JOURNEY.md)

Upstream code explicitly restricts publishing solutions. This report links and
describes techniques without incorporating third-party implementation text.
The upstream README also documents invalid early scores from agents changing
tests or enabling intentionally disabled cores. Keep the reference and evaluator
fixed. [Official task and validation warning](https://github.com/anthropics/original_performance_takehome)

## Ranked experiments for our engine

These are engineering inferences, not demonstrated GPU speedups from the puzzle.

1. **Profile the current winning graph, then fuse remaining small operations.**
   Residual-add/RMSNorm and Q/K norm + RoPE + cache write are natural candidates.
   Measure eliminated launches and intermediate traffic. Preserve every BF16
   rounding boundary; integer algebraic identities do not justify floating-point
   reassociation. Retain native prefill until an alternative passes TTFT.
2. **Tune decode attention for actual bottlenecks.** Benchmark split-KV partitions,
   tiles and warp counts against folded GQA on the same shapes. Reuse each KV head
   across its four query heads. Track reduction overhead and register pressure;
   less arithmetic alone does not establish lower latency.
3. **Tune small-batch projections and LM head.** Compare existing packed native
   GEMMs with BF16 GEMV/small-M kernels at batch 1/4/16 and extra synthetic sizes.
   Bound expected gains using measured bytes moved and time per operator.
4. **Search a small, explicit configuration space.** Reuse modular switches;
   retain failed trials and evaluate combinations after individual wins. Count
   compile/warmup costs, and confirm finalists with a separate official run.
5. **Only then consider a persistent full-block design.** Simulator scheduling
   success does not demonstrate safe GPU grid synchronization or good occupancy.
   Require a measured bottleneck that the design removes before undertaking it.

Fixed-shape specialization is part of the puzzle's published scoring contract.
Dryft has hidden shapes, so specialize on runtime shape with correct fallbacks;
never bake in public workloads or prompt contents. Tree caching is not evidence
for approximate KV pruning, additional drafter weights, or quantization.
Our exact BF16/runtime restrictions continue to apply.

The useful transfer is **measure the binding resource, eliminate its work, then
re-profile**. Puzzle cycles and claimed hundredfold speedups cannot be converted
to Dryft TPS. Our objective remains official hidden-workload geometric-mean TPS
with correctness, TTFT/TPOT, memory and stability gates, not one public batch's
throughput. This research supports the active GPU work rather than replacing it.
