# Claude Fable 5.1 collaboration

On 2026-09-19 the local Claude CLI completed a research request using
`--model claude-fable-5-1`. Its JSON model usage confirms that model, and
`is_error` is false. Raw response is retained in ignored
`results/claude-fable-5-1-research.json`. SSH hostname `fable` still does not
resolve; collaboration used the local CLI, not SSH. A constrained follow-up
was sent in the same Claude session.

## Reviewed recommendations

1. Whole-step CUDA graph with static cache and a device-position mask is the
   strongest next hypothesis. B1 and B16 step times being similar suggests
   substantial dispatch or shared-weight costs; this is not a kernel profile.
2. Test packed QKV and gate/up projections after graph behavior is known.
3. If masked static SDPA becomes the bottleneck, test GQA-aware split-KV decode
   attention with FP32 online softmax and exact initialized-slot masking.
4. Weight-free fixed-shape speculative verification may help small batches,
   depending on draft acceptance. This needs measurement, not acceptance guesses.

These recommendations overlap the queued graph, graph_hybrid, graph_norms,
packed, and custom_attention experiments. The current custom attention kernel
is nonsplit; split-KV remains a possible follow-up after actual graph results.
All performance estimates from the response are unmeasured hypotheses.

## Advice rejected or corrected

- No continuous batching across independent calls: the harness fixes the batch.
- No sampling, top-p work or EOS stopping: the contract is fixed-length greedy.
- Exact token matching and max-logit-difference 0.01 are not the official
  correctness criterion. The judge uses teacher-forced logit deficit <=2.0.
- A memory-bandwidth estimate for one non-speculative B1 step is not an
  absolute bound on speculative TPS or the hidden-workload geometric mean.
- Repacking is algebraically identical but different GEMM shapes can alter
  BF16 arithmetic ordering. Official numerical validation remains necessary.
- Fully masked rows with finite mask values can still produce meaningless
  attention. Every evaluated decode row must have initialized visible keys.

The 2000 official TPS goal remains unverified. Unknown hidden workload shapes
prevent turning per-batch throughput estimates into a promised official score.

## Follow-up and resulting experiments

The second response completed successfully in the same Fable session (raw:
`results/claude-fable-followup.json`). Its concrete suggestion is now implemented
as `folded_gqa` and `graph_folded`: for single-token decode only, reshape Q from
`[B,32,1,128]` to `[B,8,4,128]`, attend against the eight native KV heads with
`is_causal=False`, and restore head layout afterward. The four rows are query
heads at one absolute position, not four successive positions. Prefill and
multi-token verification retain the ordinary attention path. Graph capacity is
rounded to eight-token alignment, with padded positions explicitly masked.

This removes the explicit KV repetition in our adapter. Backend choice and
performance remain unverified until H100 runs; model-level regression and the
official teacher-forced checks must pass. No speedup is claimed from reshaping
alone. Fable's labels saying API facts were verified were based on recollection,
not fresh source inspection, so we do not treat those labels as verification.

We also clarified that graph objects and shape buffers may persist across calls;
only prompt-dependent content and positions must reset. Capture should occur
during warmup, not recur for each measured prompt of the same shape.

## Code review and measured-result follow-up

The third review (`results/claude-fable-code-review.json`) motivated early
option validation and installing custom attention independently of other flags.
Those fixes are implemented and locally tested. Existing presets already
satisfied the option dependencies. The review found no token-position,
head-fold mapping or speculative cache-crop error in the supplied code.

Its claim that mask alignment must be 16 elements was rejected after checking
the actual [PyTorch 2.5.1 source](https://raw.githubusercontent.com/pytorch/pytorch/v2.5.1/aten/src/ATen/native/transformers/attention.cpp):
`preprocess_mask` uses `mem_eff_alignment = 8`. The implementation retains 8.

The fourth response (`results/claude-fable-graph-results.json`) recommends norm
fusion inside graph decode. Its bandwidth calculations use incorrect model
dimensions (4 KV heads, 28 layers, and a 7B weight estimate), so those numbers
and resulting cost attributions are discarded. Norm fusion remains worth
testing because of our own paired measurements. The prioritized graph_fused
candidate combines native prefill, folded heads, all norms, packed projections
and SwiGLU; standalone candidates remain queued for attribution if needed.
# Follow-up fusion review

Confirmed another response from `claude-fable-5-1`, stored locally in
`results/claude-fable-next-fusion.json`. It reviewed the residual norm's BF16
boundaries and recommended combining Q/K per-head norm and RoPE next.
The proposed kernel must round normalized values, learned-weight products,
both RoPE products, and their final sum at the same boundaries as eager.
FP32 reduction order remains a validation concern; this review is not GPU proof.
Its estimated millisecond savings and claims about rsqrt lowering were not
measured or independently established. Profile or benchmark before relying on
them. Start with norm/RoPE fusion before coupling it to static cache writes.
