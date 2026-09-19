"""Batch only minimal rigid proposals; preserve sample order and full consensus checks."""

import numpy as np

from ..rigid import MAX_GRAVITY_DEG, MAX_ORIGIN_M


def minimal_transforms(source: np.ndarray, target: np.ndarray, seed: int):
    rng = np.random.default_rng(seed)
    indices = np.array([rng.choice(len(source), 3, replace=False) for _ in range(700)])
    a, b = source[indices], target[indices]
    mean_a, mean_b = a.mean(axis=1), b.mean(axis=1)
    a, b = a - mean_a[:, None, :], b - mean_b[:, None, :]
    spread_a, spread_b = (np.linalg.svd(p, compute_uv=False)[:, 1] for p in (a, b))
    u, _, vt = np.linalg.svd(a.transpose(0, 2, 1) @ b)
    v, ut = vt.transpose(0, 2, 1), u.transpose(0, 2, 1)
    sign = np.ones((len(indices), 3))
    sign[:, 2] = np.linalg.det(v @ ut)
    rotation = (v * sign[:, None, :]) @ ut
    translation = mean_b - (rotation @ mean_a[:, :, None])[:, :, 0]
    gravity = np.degrees(np.arccos(np.clip(rotation[:, 1, 1], -1, 1)))
    valid = (np.minimum(spread_a, spread_b) >= 0.06) & (gravity <= MAX_GRAVITY_DEG)
    valid &= np.linalg.norm(translation, axis=1) <= MAX_ORIGIN_M
    for i in np.flatnonzero(valid):
        transform = np.eye(4)
        transform[:3, :3] = rotation[i]
        transform[:3, 3] = translation[i]
        yield transform
