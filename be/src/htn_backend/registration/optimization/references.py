"""Select room reference views using proposal evidence only, never validation views."""

from .matches import prefetch


def select_references(training, reference, match):
    if len(reference) <= 5:
        return reference
    prefetch(match, training, reference)
    scores = [sum(len(match(source, target)[0]) for source in training) for target in reference]
    # Stable ties and original order preserve deterministic downstream geometry sampling.
    chosen = sorted(sorted(range(len(reference)), key=lambda i: (-scores[i], i))[:5])
    return [reference[i] for i in chosen]
