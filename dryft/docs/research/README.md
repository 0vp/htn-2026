# Optimization research and experiment order

Reviewed September 19, 2026 against the fixed challenge runtime. Research is not a performance result: no optimized engine has been implemented or measured.

## Recommended path

1. **Establish TTFT margin.** Repeat/profile the unchanged engine, then test the supplied RMSNorm fusion incrementally and bypass generic model wrappers. The current B1 failure is only about 1.43 ms above its observed gate; its cause remains unproven.
2. **Test native GQA before custom attention.** PyTorch 2.5.1 supports `enable_gqa=True` for CUDA Flash/math backends; Transformers 4.51.3 instead expands KV heads. Verify actual backend selection, numerical fidelity, and copying costs. Full prefill and single-token decode require different causal handling.
3. **Preallocate KV and capture one-token decode.** Stable buffers, device-side position/valid length, fresh state per generation, and host streaming outside capture. Retain a separate prefill implementation. This is the strongest general decode hypothesis, not a guaranteed speedup.
4. **Fuse more only where profiles justify it.** Q/K norm + RoPE/cache write, BF16-preserving SwiGLU, packed QKV and gate/up. Keep each change isolated until verified.
5. **Tune shape-specific matrix and attention kernels.** Small-batch GEMV, native GQA attention, optional split-KV, and LM-head selection. Split-KV can cost more than it saves at short contexts. LM-head fusion must retain native logits rounding and lowest-index tie handling.
6. **Defer speculative and persistent kernels.** Exact prompt lookup avoids alternate weights, but verification/rollback and latency need proof. Megakernels require safe synchronization and may sacrifice occupancy. Neither is the first experiment.

This combines the TTFT-first and decode-first research priorities: clear every gate while increasing end-to-end hidden-workload throughput. No global SOTA claim is supportable without comparable official results.

## Evidence and detailed reviews

- [Prefill and TTFT](prefill.md): numerical boundaries, compatible native GQA experiment, measurement plan.
- [Decode](decode.md): static cache, CUDA graphs, split-KV, projections and vocabulary selection.
- [Modern inference systems](sota.md): algorithm ideas versus dependencies unavailable in this runtime.
- [Claude research request](claude-prompt.md): independent review context, excluding credentials and private application code.
- [Claude review and corrections](claude.md): completed locally using authenticated `claude -p` with WebSearch/WebFetch. Both SSH hostnames were unresolved. The raw response contains incorrect correctness advice and unverified estimates; explicit corrections precede it. Its recommendations inform hypotheses, not requirements.

Primary anchors: [pinned PyTorch SDPA](https://github.com/pytorch/pytorch/blob/v2.5.1/torch/nn/functional.py), [pinned Transformers adapter](https://github.com/huggingface/transformers/blob/v4.51.3/src/transformers/integrations/sdpa_attention.py), [CUDA graphs](https://pytorch.org/blog/accelerating-pytorch-with-cuda-graphs/), and [GPT-fast](https://pytorch.org/blog/accelerating-generative-ai-2/). Published speedups in other models/hardware, quantized configurations, or serving workloads are not predictions for this challenge.

## Acceptance protocol

Keep an untouched control. For each isolated candidate, check operation outputs, prefill logits, multiple cached steps, and consecutive different prompts. Cover public shapes and additional boundary shapes; never specialize to assumed hidden cases. Record commit, runtime, benchmark digest, initialization/warmup, selected attention backend, correctness, TTFT, TPOT, complete-generation TPS, peak memory, and sample spread. Microbenchmarks diagnose; the official host-streaming run decides acceptance. Preserve failed runs.

Full FlashAttention/FlashInfer/TensorRT-LLM/serving-framework installations are not a shortcut into a Python/Triton-only fixed runtime. Their algorithms may be useful, but every imported API, source dependency, cast boundary, compile budget, and license needs checking before reuse.
