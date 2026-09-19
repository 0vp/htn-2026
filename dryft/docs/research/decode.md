# Decode optimization research

Research date: 2026-09-19. No kernels changed or GPU experiments performed.
Recommendations below are hypotheses to benchmark, not measured speedups.
Read against the local engine contract and optimization guide: BF16
Qwen3-4B-Instruct-2507, one H100, PyTorch 2.5.1, Triton 3.1.0,
Transformers 4.51.3, source-only submission.

## Recommended order

| Priority | Experiment | Reason and acceptance criterion |
| --- | --- | --- |
| 1 | Static cache plus one-token CUDA graph | Remove growing cache copies and repeated CPU dispatch. Preserve native prefill initially; improve TPOT without worsening TTFT. |
| 2 | Fuse norms, Q/K norm plus RoPE/cache write, and SwiGLU | Reduce small launches and intermediates while preserving BF16 cast boundaries. Validate one operation at a time. |
| 3 | Native-GQA Triton decode attention | Read eight KV heads directly instead of expanding to 32. Compare ordinary and split-KV schedules by shape. |
| 4 | Pack QKV and gate/up projections | Reduce dispatch and input rereads, retaining BF16 matrix outputs. Compare with existing cuBLAS-backed linears. |
| 5 | Small-batch projection and LM-head kernels | Pursue only after profiles show remaining matrix bandwidth/launch costs. Keep larger-batch GEMM dispatch separate. |

The existing batch-1 TTFT failure makes prefill a parallel priority: a decode
speedup alone cannot clear the first-token gate. Overall throughput includes
prefill, and hidden shapes prohibit tuning solely for the three public cases.

## Static cache and graphs

CUDA graph replay reuses fixed addresses and arguments; warm up on a side
stream and retain input/output allocations. This mechanism predates the pinned
runtime and is available through `torch.cuda.CUDAGraph`/`torch.cuda.graph`.
[PyTorch CUDA graphs](https://pytorch.org/blog/accelerating-pytorch-with-cuda-graphs/).

Proposed implementation: allocate `[B,8,capacity,128]` K and V per layer,
plus persistent token, absolute-position, valid-length and output buffers.
Warm the actual shape, then capture exactly one decode step. Change device
buffer contents in place; do not close over a Python length that remains
constant on replay. Retain a separate causal prefill path. Initially allocate
only the current workload capacity, not the model's maximum context.

All graph kernels must mask positions beyond valid length. Reset position and
logical length at each generation, overwrite used slots, and ensure stale
values cannot affect reductions. Test two different consecutive prompts and
the first token following prefill. Stream host token lists outside capture;
computing all output tokens before the first yield would defeat TTFT.

PyTorch's GPT-fast work supports the general combination of reduced Python
overhead and static caches, but its quantization and reported model-specific
speedups are not transferable to this BF16 challenge.
[GPT-fast discussion](https://pytorch.org/blog/accelerating-generative-ai-2/).

## Grouped-query decode attention

The exact pinned HF adapter calls `repeat_kv` before SDPA and makes Q/K/V
contiguous. Direct indexing `kv_head = query_head // 4` avoids that expansion.
The adapter also derives causality from query length when no mask is supplied;
this is not sufficient for a fixed-capacity cache.
[Transformers 4.51.3 SDPA source](https://raw.githubusercontent.com/huggingface/transformers/v4.51.3/src/transformers/integrations/sdpa_attention.py).

Flash-Decoding divides the KV sequence across parallel programs and combines
partial outputs using their log-sum-exp statistics. Its benefit depends on
available parallelism and context length; a second reduction kernel can lose
at short contexts. Implement the algorithm in Triton rather than assuming
FlashAttention or xFormers is installed. Test a nonsplit variant first, then
split counts conditioned on batch and valid length.
[Flash-Decoding authors' explanation](https://pytorch.org/blog/flash-decoding/).

Suggested mapping: one program handles a KV head and its four query heads,
with optional sequence partitions. Keep softmax statistics/reduction FP32,
apply scale `1/sqrt(128)`, and preserve the native output dtype. Explicitly
handle masked/empty partitions; avoid `-inf - -inf` NaNs. Validate logits and
teacher-forced emitted-token margins after changing reduction order.

The Triton 3.1.0 attention tutorial is a version-compatible primitives
reference, not a ready-made Qwen decode implementation: adapt GQA, cache
strides, valid lengths, BF16 handling and the single-query schedule.
[Pinned Triton attention tutorial](https://github.com/triton-lang/triton/blob/v3.1.0/python/tutorials/06-fused-attention.py).

## Projection kernels and vocabulary selection

Small-batch matrix products have little reuse of the weights; arithmetic
intensity and tile occupancy explain why one tiling policy will not serve
batch 1, batch 16 and prefill equally. Benchmark a bandwidth-oriented GEMV
against tensor-core GEMM at each small batch, retaining existing linears as
the control. Packing QKV or gate/up is a lower-complexity first experiment.
[NVIDIA matrix multiplication performance guide](https://docs.nvidia.com/deeplearning/performance/dl-performance-matrix-multiplication/index.html).

The pinned Triton matmul tutorial demonstrates tiled products, FP32
accumulation, grouped launch ordering and autotuning. Its sample is FP16;
adapt and validate BF16 rather than assuming its numerical behavior applies.
Limit tuning specializations so compilation and warmup fit 300 seconds.
[Triton 3.1.0 matrix multiplication](https://github.com/triton-lang/triton/blob/v3.1.0/python/tutorials/03-matrix-multiplication.py).

The LM head has 151,936 vocabulary rows and 2,560 columns: its BF16 matrix is
777,912,320 bytes, calculated from the guide's dimensions. A tiled LM head
could compute each tile's maximum and token index, then reduce tile winners.
This removes the logits write/read but does not eliminate reading all weights;
the benefit may be modest. Keep the tied embedding weight; never prune the
vocabulary. Round to the native logits dtype before argmax and choose the
lowest token index on exact ties. An FP32 winner before BF16 rounding can
differ from the native selection. Benchmark this separately from GEMV.

## Correctness and scope boundaries

- Follow the exact Qwen3 implementation, including per-head Q/K RMSNorm,
  RoPE absolute positions, residual order and tied weights.
  [Pinned Qwen3 source](https://github.com/huggingface/transformers/blob/v4.51.3/src/transformers/models/qwen3/modeling_qwen3.py).
- Preserve explicit BF16 intermediates in fused residual/MLP/norm paths;
  retaining extra FP32 precision is not automatically native-equivalent.
- Do not rely on newer FlexDecoding, FlashAttention-3/4, or current runtime
  APIs as installed features. Source-port feasibility must be checked against
  Triton 3.1.0 and the archive/runtime restrictions.
- Quantization, approximate attention, KV pruning and output-vocabulary
  shortcuts are excluded. The tie margin is not an approximation budget.
- Full-model persistent megakernels are higher-risk research: inter-program
  synchronization, occupancy and streaming complicate correctness. Start with
  a graph of ordinary kernels before pursuing global synchronization.

## Evidence needed before accepting an optimization

Record untouched baseline and candidate TTFT, TPOT, end-to-end throughput,
memory and repeated-run spread on all public shapes plus varied lengths and
batches. Include prefill logits, multiple cached steps and consecutive
generations in correctness checks. Profile representative warm decode steps
to separate CPU dispatch, cache copies, attention and matrix products. Run
the actual stream interface as well as device microbenchmarks; CUDA events
alone omit token transfer and protocol timing. No SOTA performance claim is
supported until the official workload results demonstrate it.
