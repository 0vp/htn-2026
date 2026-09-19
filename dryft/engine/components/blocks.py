"""Composable decoder-block replacements, retaining the HF return contract."""
from kernels.residual_norm import residual_norm


def residual_block(self, hidden_states, attention_mask=None, position_ids=None,
                   past_key_value=None, output_attentions=False, use_cache=False,
                   cache_position=None, position_embeddings=None, **kwargs):
    residual = hidden_states
    hidden_states = self.input_layernorm(hidden_states)
    hidden_states, attention_weights = self.self_attn(
        hidden_states=hidden_states, attention_mask=attention_mask,
        position_ids=position_ids, past_key_value=past_key_value,
        output_attentions=output_attentions, use_cache=use_cache,
        cache_position=cache_position, position_embeddings=position_embeddings,
        **kwargs)
    residual, hidden_states = residual_norm(
        hidden_states, residual, self.post_attention_layernorm.weight,
        self.post_attention_layernorm.variance_epsilon)
    hidden_states = residual + self.mlp(hidden_states)
    return (hidden_states, attention_weights) if output_attentions else (hidden_states,)
