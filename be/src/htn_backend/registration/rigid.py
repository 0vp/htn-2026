"""Metric rigid fitting and gravity-aware robust hypotheses. No ground-truth initialization."""

import numpy as np

MAX_GRAVITY_DEG = 8
MAX_ORIGIN_M = 12


def fit(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    a, b = source - source.mean(0), target - target.mean(0)
    u, _, vt = np.linalg.svd(a.T @ b)
    sign = np.eye(3)
    sign[2, 2] = np.linalg.det(vt.T @ u.T)
    result = np.eye(4)
    result[:3, :3] = vt.T @ sign @ u.T
    result[:3, 3] = target.mean(0) - result[:3, :3] @ source.mean(0)
    return result


def residuals(source: np.ndarray, target: np.ndarray, transform: np.ndarray) -> np.ndarray:
    return np.linalg.norm(source @ transform[:3, :3].T + transform[:3, 3] - target, axis=1)


def physical(transform: np.ndarray) -> bool:
    gravity = np.degrees(np.arccos(np.clip(transform[1, 1], -1, 1)))
    return bool(gravity <= MAX_GRAVITY_DEG and np.linalg.norm(transform[:3, 3]) <= MAX_ORIGIN_M)


def difference(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    angle = np.degrees(np.arccos(np.clip((np.trace(a[:3, :3] @ b[:3, :3].T) - 1) / 2, -1, 1)))
    return float(np.linalg.norm(a[:3, 3] - b[:3, 3])), float(angle)


def hypotheses(
    source: np.ndarray, target: np.ndarray, seed: int = 31
) -> list[tuple[int, np.ndarray]]:
    from .optimization.proposals import minimal_transforms

    candidates = []
    if len(source) < 12:
        return candidates
    for transform in minimal_transforms(source, target, seed):
        mask = residuals(source, target, transform) < 0.08
        count = int(mask.sum())
        if count < 12:
            continue
        transform = fit(source[mask], target[mask])
        if not physical(transform):
            continue
        count = int((residuals(source, target, transform) < 0.08).sum())
        found = False
        for i, (old_count, old) in enumerate(candidates):
            distance, angle = difference(transform, old)
            if distance < 0.12 and angle < 5:
                if count > old_count:
                    candidates[i] = (count, transform)
                found = True
                break
        if not found:
            candidates.append((count, transform))
            candidates.sort(key=lambda row: row[0], reverse=True)
            candidates = candidates[:8]
    return sorted(candidates, key=lambda row: row[0], reverse=True)
