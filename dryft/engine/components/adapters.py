from types import MethodType
import torch
from kernels.rmsnorm import rms_norm
from kernels.swiglu import swiglu
from kernels.decode_attention import decode_attention
from kernels.gemv import SmallBatchLinear
from components.blocks import residual_block
from transformers.models.qwen3.modeling_qwen3 import apply_rotary_pos_emb


class FusedNorm(torch.nn.Module):
    def __init__(self, reference):
        super().__init__()
        self.weight = reference.weight
        self.variance_epsilon = reference.variance_epsilon

    def forward(self, x):
        return rms_norm(x, self.weight, self.variance_epsilon)


def attention(self, hidden_states, position_embeddings, attention_mask, past_key_value=None,
              cache_position=None, **kwargs):
    x = hidden_states
    shape = x.shape[:-1]
    head_shape = (*shape, -1, self.head_dim)
    if hasattr(self, 'packed_qkv'):
        q, k, v = self.packed_qkv(x).split(self.qkv_sizes, dim=-1)
    else:
        q, k, v = self.q_proj(x), self.k_proj(x), self.v_proj(x)
    q = self.q_norm(q.view(head_shape)).transpose(1, 2)
    k = self.k_norm(k.view(head_shape)).transpose(1, 2)
    v = v.view(head_shape).transpose(1, 2)
    cos, sin = position_embeddings
    q, k = apply_rotary_pos_emb(q, k, cos, sin)
    if past_key_value is not None:
        k, v = past_key_value.update(k, v, self.layer_idx,
                                    {'sin': sin, 'cos': cos, 'cache_position': cache_position})
    folded = self.folded_gqa and q.shape[-2] == 1
    custom_decode = self.custom_attention and q.shape[-2] == 1
    if not self.native_gqa and not folded and not custom_decode:
        k = k.repeat_interleave(self.num_key_value_groups, dim=1)
        v = v.repeat_interleave(self.num_key_value_groups, dim=1)
    mask = attention_mask[..., :k.shape[-2]] if attention_mask is not None else None
    if folded:
        # Each row is a different query head at the SAME absolute position.
        # Therefore no causal relationship exists between these four rows.
        folded_q = q.reshape(q.shape[0], k.shape[1], self.num_key_value_groups, self.head_dim)
        result = torch.nn.functional.scaled_dot_product_attention(
            folded_q.contiguous(), k, v, attn_mask=mask, dropout_p=0.0,
            is_causal=False, scale=self.scaling).reshape(q.shape)
    elif custom_decode:
        result = decode_attention(q, k, v, mask, self.scaling)
    else:
        result = torch.nn.functional.scaled_dot_product_attention(
            q.contiguous(), k.contiguous(), v.contiguous(), attn_mask=mask,
            dropout_p=0.0, is_causal=mask is None and q.shape[-2] > 1,
            scale=self.scaling, enable_gqa=self.native_gqa)
    return self.o_proj(result.transpose(1, 2).contiguous().reshape(*shape, -1)), None


def mlp(self, x):
    if hasattr(self, 'packed_gate_up'):
        gate, up = self.packed_gate_up(x).chunk(2, dim=-1)
    else:
        gate, up = self.gate_proj(x), self.up_proj(x)
    product = swiglu(gate, up) if self.fused_activation else self.act_fn(gate) * up
    return self.down_proj(product)


def packed_linear(modules):
    weight = torch.cat([module.weight for module in modules], dim=0)
    result = torch.nn.Linear(weight.shape[1], weight.shape[0], bias=False,
                             device=weight.device, dtype=weight.dtype)
    result.weight = torch.nn.Parameter(weight, requires_grad=False)
    return result


def install(model, options):
    base = model.model
    if options.head_gemv:
        model.lm_head = SmallBatchLinear(model.lm_head)
    if options.norms != 'none':
        base.norm = FusedNorm(base.norm)
    for layer in base.layers:
        if options.residual_norm:
            layer.forward = MethodType(residual_block, layer)
        if options.norms != 'none':
            layer.input_layernorm = FusedNorm(layer.input_layernorm)
            layer.post_attention_layernorm = FusedNorm(layer.post_attention_layernorm)
        attn = layer.self_attn
        if options.norms == 'all':
            attn.q_norm, attn.k_norm = FusedNorm(attn.q_norm), FusedNorm(attn.k_norm)
        if options.packed:
            attn.qkv_sizes = tuple(m.out_features for m in (attn.q_proj, attn.k_proj, attn.v_proj))
            attn.packed_qkv = packed_linear((attn.q_proj, attn.k_proj, attn.v_proj))
            del attn.q_proj, attn.k_proj, attn.v_proj
            layer.mlp.packed_gate_up = packed_linear((layer.mlp.gate_proj, layer.mlp.up_proj))
            del layer.mlp.gate_proj, layer.mlp.up_proj
        if options.gqa or options.packed or options.folded_gqa or options.custom_attention:
            attn.native_gqa = options.gqa
            attn.folded_gqa = options.folded_gqa
            attn.custom_attention = options.custom_attention
            attn.forward = MethodType(attention, attn)
        if options.swiglu or options.packed:
            layer.mlp.fused_activation = options.swiglu
            layer.mlp.forward = MethodType(mlp, layer.mlp)
