"""Exact greedy verification of prompt-lookup proposals; batch one only."""
import torch
from transformers import DynamicCache


def proposal(history, limit):
    for width in (4, 3, 2):
        suffix = history[-width:]
        for start in range(len(history) - width - 1, -1, -1):
            if history[start:start + width] == suffix:
                return history[start + width:start + width + limit]
    return []


def generate(model, input_ids, output):
    with torch.inference_mode():
        history = list(input_ids[0])
        ids = torch.tensor([history], device='cuda:0', dtype=torch.int64)
        cache = DynamicCache()
        first = model(input_ids=ids, past_key_values=cache, use_cache=True,
                      logits_to_keep=1, return_dict=True)
        current = int(first.logits[:, -1].argmax(-1).item())
        history.append(current)
        yield [current]
        emitted = 1
        while emitted < output:
            draft = proposal(history, min(3, output - emitted - 1))
            old_length = cache.get_seq_length()
            ids = torch.tensor([[current] + draft], device='cuda:0', dtype=torch.int64)
            result = model(input_ids=ids, past_key_values=cache, use_cache=True,
                           logits_to_keep=0, return_dict=True)
            predictions = result.logits.argmax(-1)[0].tolist()
            accepted = 0
            while accepted < len(draft) and draft[accepted] == predictions[accepted]:
                accepted += 1
            tokens = predictions[:accepted + 1]
            cache.crop(old_length + accepted + 1)
            for current in tokens:
                history.append(current)
                emitted += 1
                yield [current]
