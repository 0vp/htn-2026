"""Residual addition and RMSNorm with both native BF16 rounding boundaries."""
import torch
import triton
import triton.language as tl


@triton.jit
def _add_norm(X, R, W, SUM, Y, WIDTH: tl.constexpr, EPS: tl.constexpr,
              BLOCK: tl.constexpr):
    row = tl.program_id(0)
    col = tl.arange(0, BLOCK)
    valid = col < WIDTH
    offset = row * WIDTH + col
    x = tl.load(X + offset, valid, other=0).to(tl.float32)
    residual = tl.load(R + offset, valid, other=0).to(tl.float32)
    # Eager residual addition produces BF16 before the following normalization.
    summed = (x + residual).to(SUM.dtype.element_ty)
    tl.store(SUM + offset, summed, valid)
    value = summed.to(tl.float32)
    variance = tl.sum(value * value, 0) / WIDTH
    normalized = (value * tl.rsqrt(variance + EPS)).to(Y.dtype.element_ty)
    weight = tl.load(W + col, valid, other=0).to(tl.float32)
    tl.store(Y + offset, normalized.to(tl.float32) * weight, valid)


def residual_norm(x: torch.Tensor, residual: torch.Tensor,
                  weight: torch.Tensor, eps: float) -> tuple[torch.Tensor, torch.Tensor]:
    x, residual = x.contiguous(), residual.contiguous()
    width = x.shape[-1]
    summed, normalized = torch.empty_like(x), torch.empty_like(x)
    _add_norm[(x.numel() // width,)](
        x, residual, weight, summed, normalized, width, eps,
        triton.next_power_of_2(width), num_warps=4, enable_fp_fusion=False)
    return summed, normalized
