"""Independent experiment switches; keep baseline as the default."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Options:
    norms: str = 'none'
    direct: bool = False
    gqa: bool = False
    static: bool = False
    graph: bool = False
    swiglu: bool = False
    packed: bool = False
    custom_attention: bool = False
    speculative: bool = False
    head_gemv: bool = False


VARIANTS = {
    'baseline': Options(),
    'norms': Options(norms='hidden'),
    'all_norms': Options(norms='all'),
    'direct': Options(direct=True),
    'gqa': Options(gqa=True),
    'static': Options(direct=True, static=True),
    'graph': Options(direct=True, static=True, graph=True),
    'swiglu': Options(swiglu=True),
    'packed': Options(packed=True),
    'custom_attention': Options(gqa=True, custom_attention=True),
    'speculative': Options(speculative=True),
    'head_gemv': Options(head_gemv=True),
    'combined': Options(norms='all', direct=True, gqa=True, static=True,
                        graph=True, swiglu=True, packed=True),
}
ACTIVE = 'all_norms'
