"""Validate loop constraints and convert ARKit camera axes to native OpenCV axes."""

import numpy as np


def encode_edges(edges):
    if len(edges) > 8:
        raise ValueError("too many pending loop constraints")
    result = []
    basis = np.diag([1, -1, -1, 1])
    for edge in edges:
        source, target = edge["from_timestamp_ns"], edge["to_timestamp_ns"]
        pose = np.asarray(edge["to_T_from"], dtype=float)
        if (
            type(source) is not int
            or type(target) is not int
            or not 0 <= target < source < 2**63
            or pose.shape != (4, 4)
            or not np.isfinite(pose).all()
            or not np.allclose(pose[3], [0, 0, 0, 1])
            or not np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), atol=1e-6)
            or not np.isclose(np.linalg.det(pose[:3, :3]), 1, atol=1e-6)
        ):
            raise ValueError("invalid loop constraint")
        result.append(
            dict(
                from_timestamp_ns=source,
                to_timestamp_ns=target,
                to_T_from=(basis @ pose @ basis).tolist(),
            )
        )
    return result
