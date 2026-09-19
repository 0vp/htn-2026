import torch
import triton
import triton.language as tl


@triton.jit
def _swiglu(G, U, Y, N: tl.constexpr, WIDTH: tl.constexpr,
            GS: tl.constexpr, US: tl.constexpr, BLOCK: tl.constexpr):
    i = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
    row, col = i // WIDTH, i % WIDTH
    g = tl.load(G + row * GS + col, i < N, other=0).to(tl.float32)
    u = tl.load(U + row * US + col, i < N, other=0).to(tl.float32)
    # Match eager SiLU's BF16 output before the independent multiplication.
    activated = (g / (1.0 + tl.exp(-g))).to(Y.dtype.element_ty).to(tl.float32)
    tl.store(Y + i, activated * u, i < N)


def swiglu(gate, up):
    shape = gate.shape
    width = gate.shape[-1]
    gate = gate.reshape(-1, width)
    up = up.reshape(-1, width)
    out = torch.empty(gate.shape, device=gate.device, dtype=gate.dtype)
    _swiglu[(triton.cdiv(gate.numel(), 256),)](
        gate, up, out, gate.numel(), width, gate.stride(0), up.stride(0), 256,
        enable_fp_fusion=False)
    return out.reshape(shape)
