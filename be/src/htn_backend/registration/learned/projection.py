"""Vectorized measured-depth lifting for normalized native RGB pixel centers."""

import numpy as np


def lift(frame, normalized):
    h = frame.header
    normalized = np.asarray(normalized, dtype=np.float64).reshape(-1, 2)
    if len(normalized) > 1600 or not np.isfinite(normalized).all():
        raise ValueError("invalid learned keypoints")
    pixels = normalized * [h.depth_width, h.depth_height] - 0.5
    indices = np.rint(pixels).astype(np.int64)
    x, y = indices.T
    valid = (x >= 1) & (x < h.depth_width - 1) & (y >= 1) & (y < h.depth_height - 1)
    candidates = np.flatnonzero(valid)
    x, y = x[candidates], y[candidates]
    z = frame.depth[y, x].astype(np.float64)
    patches = np.stack([frame.depth[y + dy, x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
    good = (frame.confidence[y, x] >= 2) & (z > 0.15) & (z < 5)
    good &= np.isfinite(patches).all(0) & (np.ptp(patches, axis=0) <= 0.12 + 0.02 * z)
    candidates, z = candidates[good], z[good]
    uv = pixels[candidates]
    points = np.full((len(pixels), 3), np.nan)
    measured = np.column_stack(((uv[:, 0] - h.cx) * z / h.fx, (uv[:, 1] - h.cy) * z / h.fy, z))
    if h.camera_convention == "arkit":
        measured *= [1, -1, -1]
    pose = np.array(h.camera_to_world).reshape(4, 4, order="F")
    points[candidates] = measured @ pose[:3, :3].T + pose[:3, 3]
    return points
