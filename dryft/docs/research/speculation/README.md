# Speculative decoding experiments

## Choice for this challenge

Our first candidate is request-local adaptive suffix lookup with exact target
verification. This is an engineering hypothesis, not a measured winner or a
full reproduction of SuffixDecoding. It uses a bounded suffix dictionary and
linear draft chains, not a suffix tree or tree-attention verifier.

| Method | Fit and decision |
| --- | --- |
| Fixed prompt lookup | No extra weights; benchmark as the simple control. |
| Adaptive suffix lookup | No extra weights; indexed lookup and acceptance feedback; benchmark next. |
| Batched adaptive suffix | Same verifier, shortest common accepted prefix; benchmark separately because one poor sequence can erase batch gains. |
| EAGLE/Medusa or external small drafter | Trained auxiliary weights are not provided and cannot be submitted. Not deployable under this contract. |
| LayerSkip early exit | Documented path assumes early-exit training; do not assume pinned Qwen has that training. |
| Draft-and-Verify layer skipping | Weight-free research alternative; needs separate draft cache, layer-selection experiments and full verification. Not yet implemented or benchmarked. |
| Suffix trees/SAM and tree verification | Promising further work; library runtimes cannot simply be installed in this source-only environment. |

The implementation deliberately discards all lookup state on each generate.
Published cross-request reuse gains therefore do not directly transfer here.
No hidden workload text, stored corpora, or weights are added.

## Implementation and validation

`components/proposals.py` owns indexed suffix proposals and strict first-mismatch
acceptance. `components/speculation.py` owns the shared target verification loop.
Modes are `speculative` (fixed, B1), `suffix` (adaptive, B1), and `suffix_batch`
(adaptive, all batches). Larger batches use native decode in B1-only modes.

Adaptive lookup starts at two draft tokens, increases up to six after full
acceptance, reduces after rejection, and pauses drafting for four steps after
two zero-acceptance verifications. These are experiment settings, not established
optimal parameters. Only committed tokens update the index.

Each multi-token forward has an explicit absolute-position causal mask. After
verification, crop the KV cache to old length plus accepted count plus one.
The emitted correction/bonus token remains uncached until the next forward.
For batches, every row uses the minimum accepted prefix, keeping cache lengths
aligned while emitting the correct next token independently per sequence.
The first token is yielded before index construction. Output length never
depends on EOS and drafts are clipped to the remaining token budget.

Local tests cover mismatch truncation, request isolation, lookup growth,
adaptive backoff, remaining-length boundaries and batch acceptance. They do
not validate CUDA arithmetic or the whole model. Official H100 runs check the
model output, latency, memory, variability and throughput. Compare same-spec
scores and paired native latency ratios; hardware drift can change raw scores.
Research and implementation are complete; performance results remain pending.

## Primary sources

- [SuffixDecoding paper](https://arxiv.org/abs/2411.04975): adaptive model-free
  speculation; reported improvements focus on repetitive agent workloads.
- [vLLM suffix documentation](https://raw.githubusercontent.com/vllm-project/vllm/main/docs/features/speculative_decoding/suffix.md): reference integration,
  not a compatible dependency to add to the pinned runtime.
- [Transformers 4.51.3 strategies](https://huggingface.co/docs/transformers/v4.51.3/generation_strategies): prompt lookup,
  batch limitation of assisted generation, and early-exit training assumption.
- [Pinned candidate-generator source](https://raw.githubusercontent.com/huggingface/transformers/v4.51.3/src/transformers/generation/candidate_generator.py):
  implementation reference for the installed version.
- [Draft & Verify](https://arxiv.org/abs/2309.08168): training-free layer-skipping
  drafting with full-model verification.
- [SAM Decoding](https://arxiv.org/abs/2411.10666): suffix-automaton retrieval
  proposals, including dynamic and corpus-backed modes.
