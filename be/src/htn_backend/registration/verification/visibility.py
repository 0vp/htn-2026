"""Restrict coverage checks to camera frusta, without nearest-surface selection."""

import numpy as np


def visible_reference(reference, source_keys, target_from_source):
    points = np.asarray(reference.points)
    visible = np.zeros(len(points), dtype=bool)
    calibrated = False
    for key in source_keys:
        frame = getattr(key, "frame", None)
        if frame is None:
            continue
        calibrated = True
        h = frame.header
        pose = target_from_source @ key.pose
        camera = (points - pose[:3, 3]) @ pose[:3, :3]
        if h.camera_convention == "arkit":
            camera *= [1, -1, -1]
        z = camera[:, 2]
        u = camera[:, 0] * h.fx / np.maximum(z, 1e-8) + h.cx
        v = camera[:, 1] * h.fy / np.maximum(z, 1e-8) + h.cy
        visible |= (
            (z >= 0.15)
            & (z <= 5)
            & (u >= 0)
            & (u < h.depth_width)
            & (v >= 0)
            & (v < h.depth_height)
        )
    return reference.select_by_index(np.flatnonzero(visible)) if calibrated else reference
