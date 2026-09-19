"""Small untimed regression check against untouched model before patching."""
import torch


def reference_cases(model):
    cases = []
    # Distinct consecutive prompts exercise state reset without reusing benchmark data.
    for batch, length, offset in [(1, 17, 101), (2, 23, 503)]:
        ids = [[(offset + row * 31 + col * 7) % model.config.vocab_size
                for col in range(length)] for row in range(batch)]
        current = torch.tensor(ids, dtype=torch.int64, device='cuda:0')
        cache = None
        tokens = []
        with torch.inference_mode():
            for _ in range(3):
                out = model(input_ids=current, past_key_values=cache, use_cache=True,
                            logits_to_keep=1, return_dict=True)
                current = out.logits[:, -1].argmax(-1, keepdim=True)
                tokens.append(current[:, 0].tolist())
                cache = out.past_key_values
        cases.append((ids, tokens))
    return cases


def verify(engine, cases):
    for ids, expected in cases:
        actual = list(engine.generate(ids, len(expected)))
        if actual != expected:
            raise RuntimeError('Untimed baseline regression check failed on consecutive prompts')
    print('Untimed baseline token regression: passed (prefill + 2 cached steps, B1/B2)', flush=True)
