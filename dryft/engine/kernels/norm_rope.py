"""Head RMSNorm and RoPE, preserving each eager BF16 cast boundary."""
import torch
import triton
import triton.language as tl


@triton.jit
def _norm_rope(X, W, COS, SIN, Y, XS0: tl.constexpr, XS1: tl.constexpr,
               XS2: tl.constexpr, XS3: tl.constexpr,
               CS0: tl.constexpr, CS1: tl.constexpr, CS2: tl.constexpr,
               SS0: tl.constexpr, SS1: tl.constexpr, SS2: tl.constexpr,
               CB: tl.constexpr, SB: tl.constexpr, T: tl.constexpr,
               H: tl.constexpr, D: tl.constexpr, EPS: tl.constexpr):
    row = tl.program_id(0)
    head = row % H
    token = row // H % T
    batch = row // (H * T)
    col = tl.arange(0, D)
    partner = (col + D // 2) % D
    base = batch * XS0 + token * XS1 + head * XS2
    x = tl.load(X + base + col * XS3).to(tl.float32)
    scale = tl.rsqrt(tl.sum(x * x, 0) / D + EPS)
    dtype = Y.dtype.element_ty
    norm = (x * scale).to(dtype).to(tl.float32)
    weight = tl.load(W + col).to(tl.float32)
    weighted = (norm * weight).to(dtype).to(tl.float32)
    other = tl.load(X + base + partner * XS3).to(tl.float32)
    other_norm = (other * scale).to(dtype).to(tl.float32)
    other_weight = tl.load(W + partner).to(tl.float32)
    rotated = (other_norm * other_weight).to(dtype).to(tl.float32)
    rotated = tl.where(col < D // 2, -rotated, rotated)
    cos = tl.load(COS + (batch % CB) * CS0 + token * CS1 + col * CS2).to(tl.float32)
    sin = tl.load(SIN + (batch % SB) * SS0 + token * SS1 + col * SS2).to(tl.float32)
    # Eager RoPE materializes two BF16 products before their BF16 sum.
    first = (weighted * cos).to(dtype).to(tl.float32)
    second = (rotated * sin).to(dtype).to(tl.float32)
    out = ((batch * H + head) * T + token) * D + col
    tl.store(Y + out, first + second)


def norm_rope(x: torch.Tensor, weight: torch.Tensor, eps: float,
              cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """Read strided [B,T,H,D], return contiguous [B,H,T,D]."""
    batch, tokens, heads, dim = x.shape
    if dim != 128 or cos.shape[0] not in (1, batch) or sin.shape[0] not in (1, batch):
        raise ValueError('Unsupported norm/RoPE head or batch layout')
    out = torch.empty((batch, heads, tokens, dim), dtype=x.dtype, device=x.device)
    _norm_rope[(batch * tokens * heads,)](
        x, weight, cos, sin, out, *x.stride(), *cos.stride(), *sin.stride(),
        cos.shape[0], sin.shape[0], tokens, heads, dim, eps,
        num_warps=4, enable_fp_fusion=False)
    return out
