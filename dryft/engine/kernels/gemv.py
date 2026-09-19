"""Small-batch BF16 linear prototype; native GEMM remains the fallback."""
import torch
import triton
import triton.language as tl


@triton.jit
def _gemv(X, W, Y, N: tl.constexpr, K: tl.constexpr, BLOCK_N: tl.constexpr,
          BLOCK_K: tl.constexpr):
    batch = tl.program_id(1)
    n = tl.program_id(0) * BLOCK_N + tl.arange(0, BLOCK_N)
    k = tl.arange(0, BLOCK_K)
    x = tl.load(X + batch * K + k, k < K, other=0).to(tl.float32)
    w = tl.load(W + n[:, None] * K + k[None, :],
                (n[:, None] < N) & (k[None, :] < K), other=0).to(tl.float32)
    result = tl.sum(w * x[None, :], 1)
    tl.store(Y + batch * N + n, result, n < N)


class SmallBatchLinear(torch.nn.Module):
    def __init__(self, reference):
        super().__init__()
        self.weight = reference.weight

    def forward(self, x):
        shape = x.shape
        rows = x.numel() // shape[-1]
        if rows > 4:
            return torch.nn.functional.linear(x, self.weight)
        x = x.contiguous()
        n, k = self.weight.shape
        y = torch.empty((*shape[:-1], n), dtype=x.dtype, device=x.device)
        _gemv[(triton.cdiv(n, 8), rows)](x, self.weight, y, n, k, 8,
                                         triton.next_power_of_2(k), num_warps=8)
        return y
