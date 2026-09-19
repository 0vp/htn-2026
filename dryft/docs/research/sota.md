# Exact inference techniques and runtime compatibility

Research date: September 19, 2026. Read the local engine contract and complete
optimization guide before this review. These are research priorities, not measured
speedups. No engine changes or benchmark runs were made for this note.

## Recommendation

Build a small inference path around existing PyTorch BF16 matrix operations,
source-only Triton fusions, a preallocated KV cache, and one-token CUDA graphs.
Keep prefill independently optimized. Borrow algorithms from serving frameworks;
their complete installations do not fit the fixed submission runtime.

Priority order:

1. Establish a passing TTFT baseline and profile prefill versus decode separately.
2. Remove generic wrapper overhead; fuse RMSNorm and Q/K normalization plus RoPE
   with explicit reference BF16 cast boundaries.
3. Preallocate contiguous KV storage and capture single-token decode using stable
   pointers and device-resident valid lengths. Reset state between calls.
4. Add direct grouped-query decode attention, then profile packed QKV and gate/up
   projections and vocabulary projection/argmax.
5. Trial `torch.compile` only on isolated tensor paths with a bounded compile budget.
6. Consider source-only speculative verification and persistent kernels only after
   the simpler path is correct, stable, and measured.

This ordering is an engineering inference from the challenge constraints and the
sources below, not a claim of globally optimal performance.

## Technique comparison

| Technique | Relevance | Compatibility and decision |
| --- | --- | --- |
| PyTorch SDPA | Exact tiled attention already available | Retain as a prefill baseline. Inspect actual selected backend and layout costs before replacing it. |
| FlashAttention-3 | Hopper-specific BF16 attention | Hardware fits, distribution does not: upstream installation builds an extension. Cannot submit CUDA source/binaries or install it. Study its algorithm; use installed SDPA or a compatible Triton implementation. |
| FlashAttention-4 | Current CuTeDSL attention implementation | A Python API does not make its missing CuTeDSL runtime available. Not a drop-in option for Triton 3.1. |
| FlashInfer | GQA, split attention, graph-friendly workspaces | Not installed; CUDA/JIT dependencies make the whole package unsuitable. Reimplement selected dense BF16 algorithms in permitted Triton source. |
| vLLM / SGLang | Mature graphs, cache layouts, dispatch, speculation | Not drop-in dependencies. Their serving scheduler and prefix reuse solve different workloads from isolated equal-length generation. Small self-contained Triton ideas may be portable after API/license review. |
| TensorRT-LLM | Optimized graph/runtime and attention | Requires unavailable runtime/build components; engine binaries are not an allowed submission. Architectural reference only. |
| `torch.compile` | Fusion and reduced Python overhead | Available in torch 2.5.1. Compilation and graph eligibility must be tested against that version. Keep host token conversion/yield outside. |
| Persistent/mega kernels | Fewer launches and intermediate memory traffic | Permitted as Python/Triton source, but not by importing an external CUDA scheduler. High synchronization, occupancy, and portability risk. |
| Exact speculative decoding | Amortizes target weight reads across accepted tokens | Explicitly permitted. No alternate checkpoint is available: prompt lookup is a feasible proposal source. Verification/cache rollback and end-to-end benefit require proof. |

FlashAttention sources document Hopper BF16 support, extension installation, and
the newer CuTeDSL implementation. These are runtime constraints, not a judgment
that the algorithms themselves are approximate.
[FlashAttention upstream](https://github.com/Dao-AILab/flash-attention).

FlashInfer's installation and attention research distinguish kernel/runtime
integration from reusable attention scheduling ideas.
[Installation](https://docs.flashinfer.ai/installation.html),
[FlashInfer paper](https://arxiv.org/abs/2501.01005).

For framework architecture references, see
[SGLang attention backends](https://docs.sglang.io/docs/advanced_features/attention_backend),
[TensorRT-LLM overview](https://docs.nvidia.com/tensorrt-llm/), and
[PagedAttention paper](https://arxiv.org/abs/2309.06180).

## CUDA graphs versus compiler and megakernel approaches

CUDA graphs replay dependency-ordered kernels with reduced CPU launch overhead.
This fits small batches without requiring unsafe global barriers. The challenge
still requires a host token list every step, so graph only the GPU forward and
argmax; copy/stream results outside capture. Capture must not freeze a Python
position integer or read unwritten static-cache slots.
[PyTorch CUDA graphs explanation](https://pytorch.org/blog/accelerating-pytorch-with-cuda-graphs/).

`torch.compile(mode="reduce-overhead")` uses CUDA graphs where eligible; it is
not a guarantee that mutation-heavy cache code is captured. Static cache buffers,
bounded shape specializations, and a full tensor-only decode path are prerequisites
to investigate. Compare manual capture against compilation rather than layering
both indiscriminately. Exhaustive autotuning risks the 300-second load/warmup
budget. Use pinned source for option semantics:
[PyTorch 2.5.1 implementation](https://github.com/pytorch/pytorch/blob/v2.5.1/torch/__init__.py).

Mirage MPK demonstrates persistent scheduling, fused norm/linear tasks, and a
Qwen3 demo. Its runtime generates CUDA and depends on its own scheduler; it is
not source-only Triton that can simply be copied into this archive. Treat it as
evidence that scheduling research matters, not an available speedup. A custom
persistent design must establish residency and dependency correctness; block
spin-waits can deadlock. Start with operation fusion and graphs.
[Mirage implementation](https://github.com/mirage-project/mirage),
[MPK paper](https://arxiv.org/abs/2512.22219).

## Attention, cache, and exactness

The model has 32 query heads and 8 KV heads: decode can reuse each KV head for
four query heads without materializing repeated K/V. A split-KV design can expose
more parallelism for batch 1, with a second reduction merging online-softmax
states. Whether it helps short contexts requires measurement; extra scratch and
launches can erase the gain. Keep dense coverage of all valid positions.

Contiguous preallocation is the first cache experiment: inputs in a call have
equal lengths, capacity is known, and calls cannot share prompt content. Paging
mainly helps fragmentation/dynamic serving and is not automatically faster here.
At 144 KiB per cached token per sequence, allocate only necessary capacity and
include graph-private pools, weights, and scratch in peak-memory checks.

For prefill, use causal tiled attention and large matrix kernels. The current
Triton tutorial is conceptual guidance, not guaranteed Triton 3.1 code:
[Triton fused attention tutorial](https://triton-lang.org/main/getting-started/tutorials/06-fused-attention.html).
Sparse/approximate attention, KV pruning, quantization, and FP8/FP4 substitutions
are excluded even when advertised as modern inference optimizations.

## Speculation and scoring

Prompt lookup can propose repeated continuations without extra weights. Verify
every candidate with the full BF16 target; accept only the greedy matching prefix,
emit the target correction at a mismatch, and discard invalid KV positions. Batched
sequences need independent acceptance lengths and correct masks/positions. This
is harder than adding a second model call. Low acceptance can slow the run.
[Original speculative sampling paper](https://arxiv.org/abs/2302.01318),
[vLLM n-gram implementation guide](https://docs.vllm.ai/en/v0.17.1/features/speculative_decoding/n_gram/).

Do not delay the first token to build a speculative block. Score includes prefill;
decode-only wins can lose overall on short outputs. Public shapes do not rank:
official hidden workloads use an equal-weight throughput geometric mean and must
all pass TTFT/TPOT <=1.10x native, memory <=90%, and sample spread <=25%. Tune
general shape dispatch during warmup, not branches that assume only public sizes.

Every optimization needs prefill-logit and cached-step comparisons, consecutive
different prompts, full public workloads, and varied local shapes. Preserve native
BF16 boundaries, Q/K RMSNorm before RoPE, absolute positions, tied LM weights,
lowest-index argmax ties, and exactly the requested number of yielded steps.
Only official replay proves challenge correctness; no speedup claim is established
by this literature review.
