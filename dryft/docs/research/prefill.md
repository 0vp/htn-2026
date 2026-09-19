# Prefill and TTFT research

Reviewed September 19, 2026. These are ranked experiments, not measured speedups.
Scope: pinned Qwen3-4B BF16 on H100, PyTorch 2.5.1, Triton 3.1.0,
Transformers 4.51.3; Python/Triton source only. No engine changes or runs were
performed for this note.

## What the baseline establishes

[The saved baseline](../baseline.md) records B1 TTFT 33.04 ms versus native
28.74 ms: a 31.614 ms gate at 1.10x native, approximately 1.426 ms below our
observation. B4/B16 TTFT was near native. One run does not establish the cause;
repeat paired measurements before attributing this to a kernel or Python.
Optimize with margin, not just to the observed threshold. The judge measures
the arrival of the first host token, so GPU prefill alone is insufficient.

## Ranked first experiments

| Order | Experiment | Why test it | Principal check |
| --- | --- | --- | --- |
| 0 | Repeat unchanged baseline and capture a separate local CPU/CUDA profile | Distinguish measurement variation, launch gaps, copies, and GPU execution | Keep profiling out of final timing; compare all public shapes |
| 1 | Install the provided RMSNorm adapter incrementally | Already matches required cast placement; replaces repeated elementwise launches | One hidden norm, then all hidden norms, then head norms; validate each stage |
| 2 | Direct loaded-layer forward with the same attention/cache | Removes generic wrapper work while retaining familiar kernels | Full prefill and T=1 decode only until explicit masks exist |
| 3 | Fused SiLU plus up multiplication | Small interface change; reduces intermediate traffic and launch count | Round SiLU output to BF16 before multiplication, as eager execution does |
| 4 | Native SDPA GQA adapter | Avoid explicit K/V head expansion in the pinned Transformers adapter | Confirm Flash backend, output fidelity, and actual copying/latency reduction |
| 5 | Fused head RMSNorm, RoPE, optional K cache store | Removes several small operations and intermediate stores | Preserve every eager BF16 boundary and absolute positions |
| 6 | Pack QKV and gate/up weights into larger linear calls during initialization | Reduces calls; may improve shape utilization | Compare GEMM outputs and memory; larger GEMMs can select different algorithms |
| 7 | Custom BF16 Triton prefill attention | Direct GQA mapping and layout control if attention dominates | Validate causal/mask semantics, numerical behavior, and full TTFT |

Orders 1–6 are hypotheses informed by the local guide's execution graph, not a
claim that every change helps. Keep a separate prefill path; decode tuning at
M=B rows is not automatically good at prefill M=B*T rows.

## Numerical boundaries to preserve

The local optimization guide is authoritative for this engine. RMSNorm reduces
and normalizes in FP32, casts to BF16, then multiplies by its learned weight.
Q/K normalization is per 128-value head before RoPE; V has no such norm.
RoPE uses theta 5,000,000 and absolute positions. In a fused implementation,
explicitly retain BF16 products before their addition and inspect generated
code for contraction; a mathematically cleaner FP32 fusion is not equivalent.
SwiGLU must retain the SiLU result's BF16 rounding before its multiplication
with up. Retain projection output rounding before residual additions. Do not
substitute FP8, quantization, approximate attention, or discarded KV entries.
The [pinned Qwen implementation](https://github.com/huggingface/transformers/blob/v4.51.3/src/transformers/models/qwen3/modeling_qwen3.py)
is the source to compare when integrating each replacement.

For head fusion, accept actual strides or produce the attention layout directly.
The starter norm wrapper's reshape/contiguous can copy noncontiguous data; count
this cost. Preserve tied embedding/LM-head storage. The baseline already uses
last-position-only logits, so claiming that as a new optimization is incorrect.

## SDPA and FlashAttention compatibility

The [Transformers 4.51.3 SDPA adapter](https://github.com/huggingface/transformers/blob/v4.51.3/src/transformers/integrations/sdpa_attention.py)
repeats K/V to query-head count, makes Q/K/V contiguous, and invokes PyTorch
SDPA. Therefore the baseline can already use a Flash kernel; merely setting
`attn_implementation="sdpa"` is not an improvement. Inspect the selected backend
on H100 and account for adapter copies.

[PyTorch 2.5.1's exact API](https://github.com/pytorch/pytorch/blob/v2.5.1/torch/nn/functional.py)
has `enable_gqa=True`, documented for CUDA Flash and math backends. The 32:8
head ratio meets its divisibility condition. An adapter retaining eight KV
heads is a compatible experiment. Force/diagnose the Flash backend locally
before assuming dispatch succeeded. Backend changes can alter numerical
results. For square full prefill use causal attention. For single-token decode
with only valid cached keys, use noncausal attention. Non-square `is_causal`
uses upper-left alignment: it is not the offset mask needed by chunked prefill.
Explicit mask visibility must be `key_position <= cached_length + query_index`
and exclude unused capacity.

[Triton 3.1's fused-attention tutorial](https://github.com/triton-lang/triton/blob/v3.1.0/python/tutorials/06-fused-attention.py)
is a version-compatible algorithm reference, not a ready Qwen BF16 GQA module:
its demonstrated test uses FP16 and equal query/KV heads. Adapt dtype, grouped
head mapping, shapes, strides, cache ownership and masks explicitly. Never
carry over its optional FP8 route.

[FlashAttention-3](https://arxiv.org/abs/2407.08608) shows why Hopper-specific
asynchronous execution is attractive. Its published measurements are attention
kernel results, not this engine's TTFT. The pinned runtime does not promise a
`flash_attn` package and forbids shipping compiled extensions; a normal package
installation is not a deployable plan. Treat FA3 ideas as later research for
source-compatible implementation, not an available dependency or expected gain.

## Measurement and acceptance

1. Retain the untouched baseline and record candidate engine hash, runtime,
   workload shape, warmup behavior, backend, and peak GPU memory.
2. Micro-test norms at widths 128/2560 and SwiGLU width 9728, including actual
   BF16 activations, noncontiguous inputs if supported, small/large magnitudes,
   and exact cast boundaries. Compare outputs before optimizing launch shape.
3. Compare prefill logits and several cached decode steps to native; inspect
   maximum errors and token margins. A tensor test cannot replace official
   teacher-forced output verification.
4. Test two different prompts consecutively after warmup. Reset cache state;
   poison unused capacity in local tests to catch accidental reads. Cover all
   three public shapes plus nonpublic boundary shapes without assuming hidden
   workload values.
5. Measure synchronized GPU events for diagnosis and host streaming TTFT for
   acceptance, plus TPOT, total throughput, memory, and spread. Interleave
   candidate/baseline trials where possible. Reject any TTFT/TPOT regression
   that violates the gates even if an isolated kernel improves.
6. Warm every used specialization within the 300-second initialization plus
   warmup budget. Keep all samples under the contract's memory and timing
   limits. Do not benchmark only warmed individual kernels and extrapolate.

Defer chunked prefill for now: with one equal-length batch and no overlapping
requests it adds launches and offset-mask complexity without an established
benefit. Likewise, decode graphs cannot repair the first-token path unless
prefill is separately optimized. A final-layer last-position-only computation
is an interesting later exact optimization, but must prove that its K/V state
for all prompt positions remains available to future decoding.
