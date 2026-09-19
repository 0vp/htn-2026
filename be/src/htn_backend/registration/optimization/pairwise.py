"""Pair-conditioned proposals keep unrelated camera matches out of minimal samples."""

import numpy as np

from ..rigid import difference, fit, hypotheses, residuals
from ..visual_seed import visual_evidence


def supported(pairs, transform):
    result = []
    for left, right, a, b in pairs:
        evidence = visual_evidence(a, b, transform)
        if (
            evidence["inliers"] >= 12
            and evidence["fraction"] >= 0.3
            and evidence["cells"] >= 8
            and evidence["rmse_m"] <= 0.07
        ):
            result.append((left, right, a, b))
    return result


def proposals(pairs):
    candidates = []
    # Sampling within a matched image pair avoids mixing unrelated view pairs.
    for _, _, a, b in sorted(pairs, key=lambda p: len(p[2]), reverse=True)[:12]:
        for _, transform in hypotheses(a, b)[:2]:
            evidence = supported(pairs, transform)
            if len({id(p[0]) for p in evidence}) < 2:
                continue
            x, y = (np.concatenate([p[i] for p in evidence]) for i in (2, 3))
            for _ in range(2):
                mask = residuals(x, y, transform) < 0.08
                if mask.sum() >= 12:
                    transform = fit(x[mask], y[mask])
            votes = sum(visual_evidence(p[2], p[3], transform)["inliers"] for p in evidence)
            existing = next(
                (
                    i
                    for i, (_, old) in enumerate(candidates)
                    if difference(transform, old)[0] < 0.12 and difference(transform, old)[1] < 5
                ),
                None,
            )
            if existing is None:
                candidates.append((votes, transform))
            elif votes > candidates[existing][0]:
                candidates[existing] = votes, transform
    return sorted(candidates, key=lambda p: p[0], reverse=True)[:8]
