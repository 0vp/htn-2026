"""Reusable fixed-width causal verification over a request-local static cache."""
from dataclasses import dataclass

import torch
from transformers import StaticCache
from components.execution import forward
from components.proposals import SuffixLookup, accepted_prefix


@dataclass
class VerificationGraph:
    tokens: torch.Tensor
    positions: torch.Tensor
    graph: torch.cuda.CUDAGraph
    predictions: torch.Tensor


class GraphVerifier:
    """Reuse shape-dependent graphs; never reuse a preceding request's KV data."""

    def __init__(self, model):
        self.model = model
        self.shape = None
        self.graphs: dict[int, VerificationGraph] = {}

    def prepare(self, batch: int, prompt: int, output: int) -> None:
        shape = (batch, prompt, output)
        if self.shape == shape:
            return
        self.graphs.clear()
        self.capacity = (prompt + output + 4 + 7) // 8 * 8
        self.cache = StaticCache(
            config=self.model.config, max_batch_size=batch,
            max_cache_len=self.capacity, device='cuda:0', dtype=torch.bfloat16)
        for width in (1, 2, 3, 4):
            tokens = torch.zeros((batch, width), device='cuda:0', dtype=torch.int64)
            positions = prompt + torch.arange(width, device='cuda:0')
            stream = torch.cuda.Stream()
            stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(stream):
                for _ in range(3):
                    forward(self.model, tokens, self.cache, positions,
                            self.capacity, all_positions=True)
            torch.cuda.current_stream().wait_stream(stream)
            graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(graph):
                predictions = forward(self.model, tokens, self.cache, positions,
                                      self.capacity, all_positions=True)
            self.graphs[width] = VerificationGraph(tokens, positions, graph, predictions)
        self.cache.reset()
        self.shape = shape

    def evaluate(self, rows: list[list[int]], start: int) -> list[list[int]]:
        width = len(rows[0])
        buffers = self.graphs[width]
        buffers.tokens.copy_(torch.tensor(rows, device='cuda:0', dtype=torch.int64))
        buffers.positions.copy_(start + torch.arange(width, device='cuda:0'))
        buffers.graph.replay()
        return buffers.predictions.tolist()

    def generate(self, ids: list[list[int]], output: int):
        if output <= 0:
            return
        with torch.inference_mode():
            batch, prompt = len(ids), len(ids[0])
            self.prepare(batch, prompt, output)
            self.cache.reset()
            tokens = torch.tensor(ids, device='cuda:0', dtype=torch.int64)
            prefill = self.model(input_ids=tokens, use_cache=True,
                                 logits_to_keep=1, return_dict=True)
            current = prefill.logits[:, -1].argmax(-1).tolist()
            yield current
            if output == 1:
                return
            source = prefill.past_key_values
            for target, value in zip(self.cache.key_cache, source.key_cache):
                target[:, :, :prompt].copy_(value)
            for target, value in zip(self.cache.value_cache, source.value_cache):
                target[:, :, :prompt].copy_(value)
            del source, prefill
            lookups = [SuffixLookup(list(row) + [token]) for row, token in zip(ids, current)]
            emitted, length = 1, prompt
            while emitted < output:
                remaining = output - emitted
                drafts = [lookup.propose(min(3, remaining - 1)) for lookup in lookups]
                # Four bounded widths support adaptive backoff without padding.
                draft_width = min(map(len, drafts))
                drafts = [draft[:draft_width] for draft in drafts]
                predicted = self.evaluate(
                    [[token] + draft for token, draft in zip(current, drafts)], length)
                accepted = min(accepted_prefix(draft, row)
                               for draft, row in zip(drafts, predicted))
                for lookup in lookups:
                    lookup.feedback(draft_width, accepted)
                # Rejected suffix slots remain masked. A following evaluation
                # overwrites every slot it exposes, so physical cropping is unnecessary.
                length += accepted + 1
                for step in range(accepted + 1):
                    current = [row[step] for row in predicted]
                    for lookup, token in zip(lookups, current):
                        lookup.append([token])
                    emitted += 1
                    yield current
