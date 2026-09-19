"""Exact greedy verification of prompt-lookup proposals; batch one only."""
import torch
from transformers import DynamicCache
from components.proposals import SuffixLookup, accepted_prefix


def proposal(history, limit):
    for width in (4, 3, 2):
        suffix = history[-width:]
        for start in range(len(history) - width - 1, -1, -1):
            if history[start:start + width] == suffix:
                return history[start + width:start + width + limit]
    return []


def generate(model, input_ids, output, adaptive=False):
    """Synchronous exact chain verification, sharing one cache length per batch."""
    if output <= 0:
        return
    with torch.inference_mode():
        histories = [list(row) for row in input_ids]
        ids = torch.tensor(histories, device='cuda:0', dtype=torch.int64)
        cache = DynamicCache()
        first = model(input_ids=ids, past_key_values=cache, use_cache=True,
                      logits_to_keep=1, return_dict=True)
        current = first.logits[:, -1].argmax(-1).tolist()
        for history, token in zip(histories, current):
            history.append(token)
        yield current
        # Build indexes after yielding the first token to preserve prefill TTFT.
        lookups = [SuffixLookup(history) for history in histories] if adaptive else []
        emitted = 1
        while emitted < output:
            remaining = output - emitted - 1
            drafts = ([lookup.propose(remaining) for lookup in lookups] if adaptive else
                      [proposal(history, min(3, remaining)) for history in histories])
            width = min(map(len, drafts))
            drafts = [draft[:width] for draft in drafts]
            old_length = cache.get_seq_length()
            ids = torch.tensor([[token] + draft for token, draft in zip(current, drafts)],
                               device='cuda:0', dtype=torch.int64)
            mask = None
            if width:
                positions = old_length + torch.arange(width + 1, device=ids.device)
                keys = torch.arange(old_length + width + 1, device=ids.device)
                mask = torch.zeros((width + 1, len(keys)), device=ids.device, dtype=model.dtype)
                mask.masked_fill_(keys[None, :] > positions[:, None], torch.finfo(model.dtype).min)
                mask = mask[None, None]
            result = model(input_ids=ids, past_key_values=cache, use_cache=True,
                           attention_mask=mask, logits_to_keep=0, return_dict=True)
            predictions = result.logits.argmax(-1).tolist()
            counts = [accepted_prefix(draft, predicted) for draft, predicted in zip(drafts, predictions)]
            accepted = min(counts)
            if adaptive:
                for lookup in lookups:
                    lookup.feedback(width, accepted)
            cache.crop(old_length + accepted + 1)
            for step in range(accepted + 1):
                current = [row[step] for row in predictions]
                for row, token in enumerate(current):
                    histories[row].append(token)
                    if adaptive:
                        lookups[row].append([token])
                emitted += 1
                yield current
