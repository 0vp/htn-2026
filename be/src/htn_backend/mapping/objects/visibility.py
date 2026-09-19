"""Measured free-space evidence at previously mapped object surfaces."""

import numpy as np


def evidence(frame, points):
    h = frame.header
    points = np.asarray(points, dtype=float)
    if not len(points):
        return dict(visible=0, free=0, occupied=0, occluded=0)
    points = points[np.linspace(0, len(points) - 1, min(len(points), 512), dtype=int)]
    pose = np.array(h.camera_to_world).reshape(4, 4, order="F")
    camera = (points - pose[:3, 3]) @ pose[:3, :3]
    if h.camera_convention == "arkit":
        camera *= [1, -1, -1]
    z = camera[:, 2]
    uv = camera[:, :2] / np.maximum(z[:, None], 1e-8) * [h.fx, h.fy] + [h.cx, h.cy]
    pixels = np.rint(uv).astype(int)
    valid = (
        (z > 0.15)
        & (z < 5)
        & (pixels[:, 0] >= 0)
        & (pixels[:, 0] < h.depth_width)
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] < h.depth_height)
    )
    pixels, z = pixels[valid], z[valid]
    if not len(z):
        return dict(visible=0, free=0, occupied=0, occluded=0)
    # Multiple vertices in one depth pixel are correlated evidence, not separate votes.
    _, unique = np.unique(pixels, axis=0, return_index=True)
    pixels, z = pixels[unique], z[unique]
    x, y = pixels.T
    depth = frame.depth[y, x]
    usable = (frame.confidence[y, x] >= 2) & np.isfinite(depth) & (depth > 0.15) & (depth < 5)
    delta = depth[usable] - z[usable]
    # Include two voxels plus a depth-dependent margin; never use missing depth as free.
    margin = 0.08 + 0.02 * z[usable]
    return dict(
        visible=len(delta),
        free=int(np.count_nonzero(delta > margin)),
        occupied=int(np.count_nonzero(np.abs(delta) <= margin)),
        occluded=int(np.count_nonzero(delta < -margin)),
    )
