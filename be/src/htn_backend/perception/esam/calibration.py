"""Metric, calibrated phone RGB-D to the upstream ESAM camera conventions."""

import io

import numpy as np
from PIL import Image

from ...mapping.hydra.packet import Y_TO_Z
from ..orientation import upright_quarter_turns


class InsufficientDepth(ValueError):
    """A valid capture has too little measured geometry for instance inference."""


def prepare(frame):
    h = frame.header
    if not frame.rgb_jpeg:
        raise ValueError("ESAM requires RGB")
    with Image.open(io.BytesIO(frame.rgb_jpeg)) as image:
        if image.size != (h.rgb_width, h.rgb_height):
            raise ValueError("RGB dimensions disagree with calibration")
        image = image.convert("RGB")
        image.thumbnail((640, 640), Image.Resampling.BILINEAR)
        color = np.array(image)
    valid = (
        np.isfinite(frame.depth)
        & (frame.confidence >= 1)
        & (frame.depth >= 0.15)
        & (frame.depth <= 5.0)
    )
    if valid.sum() < 20:
        raise InsufficientDepth("ESAM requires at least 20 valid depth samples")
    pose = np.array(h.camera_to_world).reshape(4, 4, order="F").copy()
    if h.camera_convention == "arkit":
        pose = pose @ np.diag([1, -1, -1, 1])
    pose[:3] = Y_TO_Z @ pose[:3]
    # Keep RGB detail for 2D masks. Upsampling depth adds no new measurements;
    # nearest-neighbour sampling preserves invalid pixels and metric depth.
    depth = np.array(
        Image.fromarray(np.where(valid, frame.depth * 1000, 0)).resize(
            (color.shape[1], color.shape[0]), Image.Resampling.NEAREST
        )
    )
    sx, sy = color.shape[1] / h.depth_width, color.shape[0] / h.depth_height
    fx, fy, cx, cy = h.fx * sx, h.fy * sy, (h.cx + 0.5) * sx - 0.5, (h.cy + 0.5) * sy - 0.5
    # Rotate all calibrated quantities together. Upright RGB with an unrotated
    # pose/depth grid would produce plausible but misplaced 3D objects.
    for _ in range(upright_quarter_turns(h)):
        width = depth.shape[1]
        color, depth = np.rot90(color).copy(), np.rot90(depth).copy()
        fx, fy, cx, cy = fy, fx, cy, width - 1 - cx
        pose[:3, :3] = pose[:3, :3] @ np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    return dict(
        color=color,
        depth_mm=depth.astype(np.float32),
        intrinsic=np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]]),
        pose=pose,
    )


def visible_pixels(frame, points):
    """Only label surfaces supported by this frame's measured depth, not occluders."""
    h = frame.header
    pose = np.array(h.camera_to_world).reshape(4, 4, order="F")
    camera = (points - pose[:3, 3]) @ pose[:3, :3]
    if h.camera_convention == "arkit":
        camera *= [1, -1, -1]
    z = camera[:, 2]
    uv = np.rint(camera[:, :2] / np.maximum(z[:, None], 1e-8) * [h.fx, h.fy] + [h.cx, h.cy]).astype(
        np.int64
    )
    inside = (
        (z >= 0.15)
        & (z <= 5)
        & (uv[:, 0] >= 0)
        & (uv[:, 0] < h.depth_width)
        & (uv[:, 1] >= 0)
        & (uv[:, 1] < h.depth_height)
    )
    uv, z = uv[inside], z[inside]
    uv, indices = np.unique(uv, axis=0, return_index=True)
    z = z[indices]
    x, y = uv.T
    valid = (frame.confidence[y, x] >= 1) & (np.abs(frame.depth[y, x] - z) <= 0.05 + 0.02 * z)
    return y[valid], x[valid]
