import torch
from transformers import DynamicCache, StaticCache


def forward(model, ids, cache, positions, capacity=None):
    base = model.model
    x = base.embed_tokens(ids)
    pos_ids = positions.unsqueeze(0)
    rope = base.rotary_emb(x, pos_ids)
    mask = None
    if capacity is not None:
        keys = torch.arange(capacity, device=ids.device)
        visible = keys.unsqueeze(0) <= positions.unsqueeze(1)
        mask = torch.zeros(visible.shape, device=ids.device, dtype=x.dtype)
        mask.masked_fill_(~visible, torch.finfo(x.dtype).min)
        mask = mask[None, None]
    for layer in base.layers:
        x = layer(x, attention_mask=mask, position_ids=pos_ids,
                  past_key_value=cache, use_cache=True, cache_position=positions,
                  position_embeddings=rope)[0]
    # Last-position normalization is independent along tokens.
    return model.lm_head(base.norm(x[:, -1:, :])).argmax(-1)


class Execution:
    def __init__(self, model, options):
        self.model, self.options = model, options
        self.shape = None

    def prepare(self, batch, prompt, output):
        shape = (batch, prompt, output)
        if shape == self.shape:
            return
        self.shape = shape
        self.capacity = prompt + output
        self.cache = StaticCache(config=self.model.config, max_batch_size=batch,
                                 max_cache_len=self.capacity, device='cuda:0', dtype=torch.bfloat16)
        self.token = torch.zeros((batch, 1), dtype=torch.int64, device='cuda:0')
        self.position = torch.tensor([prompt], dtype=torch.int64, device='cuda:0')
        self.graph = None
        if self.options.graph:
            stream = torch.cuda.Stream()
            stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(stream):
                for _ in range(3):
                    forward(self.model, self.token, self.cache, self.position, self.capacity)
            torch.cuda.current_stream().wait_stream(stream)
            self.graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(self.graph):
                self.graph_token = forward(self.model, self.token, self.cache, self.position, self.capacity)
        self.cache.reset()

    def generate(self, ids, output):
        if self.options.native_prefill:
            yield from self.generate_hybrid(ids, output)
            return
        with torch.inference_mode():
            current = torch.tensor(ids, dtype=torch.int64, device='cuda:0')
            if self.options.static:
                self.prepare(len(ids), len(ids[0]), output)
                self.cache.reset()
                cache = self.cache
            else:
                cache = DynamicCache()
            position = 0
            for step in range(output):
                if self.options.graph and step > 0:
                    self.token.copy_(current)
                    self.position.fill_(position)
                    self.graph.replay()
                    current = self.graph_token
                else:
                    positions = torch.arange(position, position + current.shape[1], device='cuda:0')
                    current = forward(self.model, current, cache, positions,
                                      self.capacity if self.options.static else None)
                position = len(ids[0]) if step == 0 else position + 1
                yield current[:, 0].tolist()

    def generate_hybrid(self, ids, output):
        """Native dynamic prefill, followed by fixed-buffer graphed decode."""
        if output <= 0:
            return
        with torch.inference_mode():
            batch, prompt = len(ids), len(ids[0])
            self.prepare(batch, prompt, output)
            tokens = torch.tensor(ids, dtype=torch.int64, device='cuda:0')
            prefill = self.model(input_ids=tokens, use_cache=True, logits_to_keep=1,
                                 return_dict=True)
            current = prefill.logits[:, -1].argmax(-1, keepdim=True)
            yield current[:, 0].tolist()
            if output == 1:
                return
            # Only initialized positions enter the graph's visible cache range.
            # Reset also removes data from the preceding prompt/warmup call.
            self.cache.reset()
            source = prefill.past_key_values
            for target, value in zip(self.cache.key_cache, source.key_cache):
                target[:, :, :prompt].copy_(value)
            for target, value in zip(self.cache.value_cache, source.value_cache):
                target[:, :, :prompt].copy_(value)
            del prefill, source
            for step in range(1, output):
                self.token.copy_(current)
                self.position.fill_(prompt + step - 1)
                self.graph.replay()
                current = self.graph_token
                yield current[:, 0].tolist()
