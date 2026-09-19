"""Back-project measured depth with an explicit ARKit/OpenCV basis conversion."""

import numpy as np

from ..capture.frame import Frame


def project(frame: Frame, stride: int = 2, mask: np.ndarray | None = None) -> np.ndarray:
    if stride < 1:
        raise ValueError("stride must be positive")
    if mask is not None and mask.shape != frame.depth.shape:
        raise ValueError("mask must be registered to the depth grid")
    h = frame.header
    rows, cols = np.mgrid[0 : h.depth_height : stride, 0 : h.depth_width : stride]
    depth = frame.depth[::stride, ::stride]
    valid = np.isfinite(depth) & (depth >= 0.1) & (depth <= 8)
    valid &= frame.confidence[::stride, ::stride] >= 1
    if mask is not None:
        valid &= mask[::stride, ::stride].astype(bool)
    z = depth[valid]
    points = np.column_stack(((cols[valid] - h.cx) * z / h.fx, (rows[valid] - h.cy) * z / h.fy, z))
    if h.camera_convention == "arkit":
        points *= np.array([1, -1, -1])
    transform = np.array(h.camera_to_world).reshape(4, 4, order="F")
    return points @ transform[:3, :3].T + transform[:3, 3]
