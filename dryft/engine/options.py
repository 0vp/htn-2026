"""Independent experiment switches; keep baseline as the default."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Options:
    norms: str = 'none'
    direct: bool = False
    gqa: bool = False
    folded_gqa: bool = False
    static: bool = False
    graph: bool = False
    native_prefill: bool = False
    swiglu: bool = False
    packed: bool = False
    custom_attention: bool = False
    speculative: bool = False
    adaptive_speculation: bool = False
    batched_speculation: bool = False
    head_gemv: bool = False

    def __post_init__(self):
        if self.norms not in ('none', 'hidden', 'all'):
            raise ValueError('Unknown norm replacement mode')
        if self.static and not self.direct:
            raise ValueError('Static cache requires direct execution')
        if self.graph and not self.static:
            raise ValueError('Graph decode requires static cache')
        if self.native_prefill and not self.graph:
            raise ValueError('Native-prefill transfer requires graph decode')
        if (self.adaptive_speculation or self.batched_speculation) and not self.speculative:
            raise ValueError('Speculation modifiers require speculative execution')
        if self.folded_gqa and self.custom_attention:
            raise ValueError('Choose folded native or custom decode attention, not both')


VARIANTS = {
    'baseline': Options(),
    'norms': Options(norms='hidden'),
    'all_norms': Options(norms='all'),
    'direct': Options(direct=True),
    'gqa': Options(gqa=True),
    'folded_gqa': Options(folded_gqa=True),
    'static': Options(direct=True, static=True),
    'graph': Options(direct=True, static=True, graph=True),
    'graph_hybrid': Options(direct=True, static=True, graph=True, native_prefill=True),
    'graph_folded': Options(direct=True, static=True, graph=True, native_prefill=True, folded_gqa=True),
    'graph_norms': Options(norms='all', direct=True, static=True, graph=True),
    'swiglu': Options(swiglu=True),
    'packed': Options(packed=True),
    'custom_attention': Options(gqa=True, custom_attention=True),
    'speculative': Options(speculative=True),
    'suffix': Options(speculative=True, adaptive_speculation=True),
    'suffix_batch': Options(speculative=True, adaptive_speculation=True, batched_speculation=True),
    'head_gemv': Options(head_gemv=True),
    'combined': Options(norms='all', direct=True, gqa=True, static=True,
                        graph=True, swiglu=True, packed=True),
}
ACTIVE = 'graph_hybrid'
