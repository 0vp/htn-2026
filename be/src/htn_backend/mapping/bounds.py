"""Upright bounds of observed surfaces, not inferred complete object extents."""

import numpy as np


def fit_upright_bounds(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    center = np.median(points, axis=0)
    if len(points) < 2:
        return center, np.full(3, 0.015), 0.0
    horizontal = points[:, [0, 2]] - center[[0, 2]]
    values, vectors = np.linalg.eigh(np.cov(horizontal.T))
    axis = vectors[:, np.argmax(values)]
    yaw = float(np.arctan2(-axis[1], axis[0]))
    c, s = np.cos(yaw), np.sin(yaw)
    rotation = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    local = (points - center) @ rotation
    # Native TSDF surfaces are already fused. Removing 5% at each end erodes
    # legitimate object boundaries; retain 98% while trimming isolated extremes.
    low, high = np.quantile(local, [0.01, 0.99], axis=0)
    center += ((low + high) / 2) @ rotation.T
    return center, np.maximum(high - low, 0.015), yaw
