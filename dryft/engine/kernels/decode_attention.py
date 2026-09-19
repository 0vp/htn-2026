"""Dense one-token GQA, online softmax over all valid keys."""
import torch
import triton
import triton.language as tl


@triton.jit
def _decode(Q, K, V, MASK, O, LENGTH: tl.constexpr, HEADS: tl.constexpr,
            KV_HEADS: tl.constexpr, QB: tl.constexpr, QH: tl.constexpr,
            KB: tl.constexpr, KH: tl.constexpr, KT: tl.constexpr,
            VB: tl.constexpr, VH: tl.constexpr, VT: tl.constexpr,
            MASKED: tl.constexpr, SCALE: tl.constexpr, BLOCK: tl.constexpr):
    head = tl.program_id(0) % HEADS
    batch = tl.program_id(0) // HEADS
    kv_head = head // (HEADS // KV_HEADS)
    d = tl.arange(0, 128)
    q = tl.load(Q + batch * QB + head * QH + d).to(tl.float32)
    maximum = tl.full((), float('-inf'), tl.float32)
    normalizer = tl.full((), 0, tl.float32)
    accumulator = tl.full((128,), 0, tl.float32)
    for start in range(tl.cdiv(LENGTH, BLOCK)):
        t = start * BLOCK + tl.arange(0, BLOCK)
        valid = t < LENGTH
        if MASKED:
            valid = valid & (tl.load(MASK + t, t < LENGTH, other=-1.0e30) > -1.0e20)
        k = tl.load(K + batch * KB + kv_head * KH + t[:, None] * KT + d[None, :],
                    valid[:, None], other=0).to(tl.float32)
        scores = tl.sum(k * q[None, :], 1) * SCALE
        scores = tl.where(valid, scores, float('-inf'))
        new_maximum = tl.maximum(maximum, tl.max(scores, 0))
        rescale = tl.exp(maximum - new_maximum)
        probabilities = tl.exp(scores - new_maximum)
        v = tl.load(V + batch * VB + kv_head * VH + t[:, None] * VT + d[None, :],
                    valid[:, None], other=0).to(tl.float32)
        accumulator = accumulator * rescale + tl.sum(probabilities[:, None] * v, 0)
        normalizer = normalizer * rescale + tl.sum(probabilities, 0)
        maximum = new_maximum
    tl.store(O + (batch * HEADS + head) * 128 + d, accumulator / normalizer)


def decode_attention(q, k, v, mask, scale):
    out = torch.empty(q.shape, dtype=q.dtype, device=q.device)
    _decode[(q.shape[0] * q.shape[1],)](
        q, k, v, mask if mask is not None else q, out, k.shape[-2], q.shape[1], k.shape[1],
        q.stride(0), q.stride(1), k.stride(0), k.stride(1), k.stride(2),
        v.stride(0), v.stride(1), v.stride(2), mask is not None, scale, 32,
        num_warps=4, enable_fp_fusion=False)
    return out
