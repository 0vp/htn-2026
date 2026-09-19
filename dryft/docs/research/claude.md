# Independent Claude review

Executed locally with claude -p; SSH hosts fable and claude were unresolved. Output below is an independent research assessment, not measured performance.

## Review corrections — read before using the raw response

- The starter already owns its generation loop; it calls the model forward, not `model.generate`. The applicable change is bypassing generic forward dispatch and dynamic cache management.
- Reject the predicted 4–6 ms decode time, percentage gains, kernel-count ranges, bandwidth utilization estimates, and claims that graphs fit comfortably in the warmup budget or eager prefill fixes TTFT. None was measured on this challenge. Profile and benchmark instead.
- Similar step times across batches do not prove CPU launch overhead; weight bandwidth and other fixed costs can also produce that pattern. The proposed 40%/80% profiling thresholds are heuristics, not established decision boundaries.
- The output rule is `max(reference_logits) - reference_logits[emitted_token] <= 2.0`, on the emitted prefix. The raw statement that a minimum margin must be above 2.0 is incorrect. Bit-identical intermediate results and identical tokens are useful diagnostics, not the platform's universal acceptance criterion. Legal reduction reorderings can change BF16 intermediates without violating the rule.
- Native logits rounding and lowest-index argmax ties must be preserved when fusing token selection. FP32 accumulation does not eliminate the need to round to the reference output dtype before choosing a token.
- Source URLs and measured performance assertions in the raw response require independent verification before use. Prefer our pinned configuration and reviewed primary sources over its mutable `main` links.

## Raw Claude response

Research complete. Below is the ranked plan with evidence, sources, and ablation/rejection criteria. Browsing worked for all sources except the Triton 3.1.0 release page, which returned only cherry-pick notes, so Hopper feature claims for Triton 3.1 are marked as hypotheses.

## What the one starter run suggests, and what it does not

The starter's step time is nearly the same at batch 1 and batch 16, which points to fixed per-step overhead rather than bandwidth.

| Case | Public TPS | Implied per-step time | Bandwidth floor per step (8 GB weights at ~3.35 TB/s) |
|---|---|---|---|
| B1 S512 O32 | 35.86 | ~27.7 ms (TPOT) | ~2.4 ms |
| B16 S512 O128 | 547.05 | ~27 ms for 16 tokens | ~2.6 ms plus KV reads |

The 36-layer forward launches roughly 500 to 700 small kernels per step through the Transformers generate loop, so a ~25 ms step at batch 1 is consistent with launch and Python overhead, not with HBM limits. That is a hypothesis from two data points. Confirm it with an Nsight Systems or torch profiler trace of five decode steps before committing: if GPU-active time per step is under 40% of wall time, overhead is the bottleneck. The B1 TTFT failure (33.04 vs 28.74 ms native) is consistent with the same story, since wrapper overhead is a larger fraction of a short 512-token prefill.

Since the score is a geometric mean of output TPS including prefill across hidden shapes, decode step time at small batch dominates the B1 and B4 cases, and prefill efficiency matters for B4 S2048 (8192 prefill tokens for 128 output tokens).

## Ranked path

1. **Own decode loop with static KV cache and manual CUDA graphs (highest value, low to medium risk).** Bypass generate entirely. Preallocate KV as [layers, B, 8, max_len, 128] BF16, keep input ids, position, and cache-length tensors as fixed device buffers, and capture one torch.cuda.CUDAGraph per (batch bucket, max-length bucket). Warmup on the side stream, then replay per token. Host token streaming copies the argmax result out after replay. Attention inside the graph must read a device-side valid-length scalar and mask uninitialized slots. Transformers 4.51.3 documents the static cache plus compile route but warns that any batch or max-length change recompiles and the first several calls are slow ([HF llm_optims 4.51.3](https://huggingface.co/docs/transformers/v4.51.3/en/llm_optims)). Manual graphs avoid the compile cost: capture takes seconds per bucket, comfortably inside the 300 s load-plus-warmup budget for a dozen buckets. vLLM's V1 design captures full graphs only for uniform decode batches and pads to a fixed set of sizes for exactly this reason ([vLLM CUDA graphs design](https://docs.vllm.ai/en/stable/design/cuda_graphs/)). Expected outcome at B1: step time drops from ~27 ms toward 4 to 6 ms, which is the largest single gain available. Measured evidence for this pattern: gpt-fast reports 104.9 tok/s for Llama-2-7B BF16 on A100 with static cache plus compile-driven graphs and no quantization ([gpt-fast README](https://github.com/pytorch-labs/gpt-fast/blob/main/README.md)), which is near 60% of that GPU's bandwidth floor.

2. **Separate prefill from decode.** Run prefill eager with SDPA flash backend (compute-bound at 512 to 8192 tokens, cuBLAS and FA2 already near peak), write KV directly into the static cache, take the last-token logits, then enter the graphed decode loop. Bucket prefill lengths to a multiple of 64 with a causal plus padding mask so the initialized-slot invariant holds. gpt-fast keeps prefill compile optional for the same reason. Also fixes the B1 TTFT gate, because native Transformers prefill overhead is the comparison point.

3. **Fused weights and low-risk fused elementwise ops.** Concatenate q/k/v into one [6144, 2560] GEMM and gate/up into one [19456, 2560] GEMM. This is re-layout of existing weights, not extra weights; state that assumption in the submission notes. Fuse in Triton: residual-add plus RMSNorm (float32 statistics, multiply the learned weight after casting back to BF16 exactly as Qwen3RMSNorm does, per the 4.51.3 source ([modeling_qwen3.py v4.51.3](https://raw.githubusercontent.com/huggingface/transformers/v4.51.3/src/transformers/models/qwen3/modeling_qwen3.py))), per-head q_norm/k_norm plus RoPE plus KV-cache write, and SiLU-gate multiply. This cuts kernel count per layer from roughly 15 to about 7 and reduces activation traffic. Gain is modest once graphs are in place (perhaps 15 to 25% of step time) but it is portable and easy to verify op by op.

4. **Native GQA and split-KV decode attention.** PyTorch 2.5 SDPA accepts enable_gqa, so avoid repeat_kv copies. For decode with 8 KV heads at batch 1, only 8 to 32 CTAs work, well under 132 SMs; Flash-Decoding's split-KV fixes this and reports near-constant attention time up to 32k context ([PyTorch Flash-Decoding blog](https://pytorch.org/blog/flash-decoding/)). For the public shapes (max 2176 context), attention is a small share of the step, so treat this as a B4 S2048 and hidden long-context win, not a headline gain. A Triton split-KV kernel (partial softmax with log-sum-exp, then reduce) is exact, so it is not "approximate attention". Whether torch 2.5.1's built-in flash kernel already splits KV for q_len 1 is unverified; measure SDPA first and only write the Triton kernel if attention exceeds ~10% of step time.

5. **Small-batch GEMV in Triton.** At batch 1 to 4, cuBLAS BF16 GEMM with M=1 is typically within 70 to 85% of bandwidth on H100; a Triton bandwidth-oriented GEMV with float32 accumulation may gain 10 to 20% on the largest matrices. Hypothesis only. Do it after items 1 to 3 because it needs per-shape benchmarking and dual code paths (cuBLAS for B16 prefill). Triton 3.1 on sm90: tl.dot uses wgmma in this era, and TMA descriptors were experimental; I could not verify the 3.1.0 notes directly, so do not depend on TMA.

6. **Tied LM head argmax.** The 151936 x 2560 head is ~0.78 GB per step, about 10% of weight traffic at batch 1. Compute the GEMM with cuBLAS then argmax; fusing argmax into a Triton GEMV that never writes logits saves under 1% and adds risk for the 2.0-logit tie check. Do the plain version only, keep float32 accumulation.

7. **Speculative decoding without extra weights (optional, gated by data).** Prompt-lookup n-gram drafting is weight-free, exact under greedy verification, and integrated in Transformers via prompt_lookup_num_tokens ([apoorvumang/prompt-lookup-decoding](https://github.com/apoorvumang/prompt-lookup-decoding)). Its gain depends entirely on input-output n-gram overlap; a 2026 systematic study found acceptance length varies strongly by dataset and position and that verification dominates ([Speculative Decoding: Performance or Illusion?](https://arxiv.org/abs/2601.11580)). It also breaks uniform-decode graphs unless you always verify a fixed k and pad. Since you must emit exactly max_new_tokens, drafted tokens beyond the limit are simply dropped. Only attempt after 1 to 4 and only if public prompts show mean accepted length above 1.5.

8. **Persistent or megakernel (reject for this submission).** Hazy Research's Llama-1B megakernel reaches 78% of H100 bandwidth versus ~50% for vLLM and SGLang, but it is CUDA C++ on ThunderKittens infrastructure, batch 1 only ([Hazy Research, No Bubbles](https://hazyresearch.stanford.edu/blog/2025-05-27-no-bubbles)). A Triton persistent kernel needs global spin-wait barriers without cooperative launch guarantees, which risks deadlock and is hard to make graph-safe. CUDA graphs capture most of the launch-gap benefit; revisit only if the profile after item 4 still shows more than 30% idle gaps.

**Not portable:** FlashAttention 3, FlashInfer, vLLM and SGLang runtimes, TensorRT-LLM, quantized Marlin kernels, and Triton 3.2+ TMA and warp-specialization APIs all fall outside Python/Triton-only, no-binaries, no-quantization rules.

## Ablations, correctness checks, rejection criteria

Run each ablation on all three public shapes with five samples, and record TTFT, TPOT, spread, and memory.

- **Profile first.** Trace five decode steps of the starter. Rejection: if GPU-active time is above 80% of wall time, deprioritize graphs and revisit kernel choices.
- **Ablation ladder.** Starter; plus own loop and static cache; plus CUDA graphs; plus fused QKV and gate-up; plus fused norm/RoPE/cache-write; plus split-KV attention; plus Triton GEMV. Keep each step only if TPS improves on the geometric mean and no gate regresses.
- **Correctness per op.** Compare each fused kernel to the 4.51.3 reference op in isolation with max absolute BF16 difference of zero, since the reference is deterministic BF16 with float32 norm statistics. Any nonzero difference in RMSNorm or RoPE is a bug, not tolerance.
- **End-to-end correctness.** Teacher-force the reference on your emitted prefix for all public prompts and for synthetic prompts at bucket edges (lengths 1, 63, 64, 65, 2047, 2048). Check that all tokens match and that the minimum logit margin stays above 2.0. Reject any change that makes a token differ.
- **Cache hygiene.** Run two consecutive calls with different prompts and different batch sizes and assert bit-identical outputs to a fresh-process run, which catches stale KV slots and graph buffer aliasing.
- **Graph stability.** Assert buffer data pointers are unchanged across 1000 replays, and pin a memory check under the 90% gate at the largest bucket.
- **Timing spread.** If any config exceeds 25% spread across five samples, look for host-side stalls (synchronizing copies inside the loop, allocator growth) before tuning kernels.
- **Compile fallback.** If you try torch.compile at all, time a cold compile per bucket; reject if the sum across buckets exceeds 120 s, leaving margin for weight load and graph capture.

Sources:
- [Qwen3-4B-Instruct-2507 config.json](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/config.json)
- [Transformers 4.51.3 Qwen3 modeling source](https://raw.githubusercontent.com/huggingface/transformers/v4.51.3/src/transformers/models/qwen3/modeling_qwen3.py)
- [Transformers 4.51.3 LLM optimization docs](https://huggingface.co/docs/transformers/v4.51.3/en/llm_optims)
- [gpt-fast README](https://github.com/pytorch-labs/gpt-fast/blob/main/README.md)
- [PyTorch Flash-Decoding blog](https://pytorch.org/blog/flash-decoding/)
- [Stanford CRFM Flash-Decoding post](https://crfm.stanford.edu/2023/10/12/flashdecoding.html)
- [vLLM CUDA Graphs design](https://docs.vllm.ai/en/stable/design/cuda_graphs/)
- [vLLM torch.compile blog](https://vllm.ai/blog/2025-08-20-torch-compile)
- [Hazy Research megakernel post](https://hazyresearch.stanford.edu/blog/2025-05-27-no-bubbles)
- [Prompt lookup decoding](https://github.com/apoorvumang/prompt-lookup-decoding)
- [Speculative Decoding: Performance or Illusion?](https://arxiv.org/abs/2601.11580)
- [Triton v3.1.0 release page](https://github.com/triton-lang/triton/releases/tag/v3.1.0)
- [NVIDIA CUDA Graph best practices for PyTorch](https://docs.nvidia.com/dl-cuda-graph/latest/torch-cuda-graph/best-practices.html)
