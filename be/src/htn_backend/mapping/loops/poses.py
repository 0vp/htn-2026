"""Use an exact native agent pose for visibility after graph optimization."""

from dataclasses import replace

import numpy as np
from scipy.spatial.transform import Rotation

from ..hydra.packet import Y_TO_Z


def corrected_frame(frame, agents):
    agents = np.asarray(agents)
    if agents.ndim != 2 or agents.shape[1] != 8 or not len(agents):
        return None
    index = int(np.argmin(abs(agents[:, 0] - frame.header.timestamp_s)))
    row = agents[index]
    if abs(row[0] - frame.header.timestamp_s) > 1e-5 or not np.isfinite(row).all():
        return None
    native = np.eye(4)
    native[:3, :3] = Rotation.from_quat(row[[5, 6, 7, 4]]).as_matrix()
    native[:3, 3] = row[1:4]
    pose = native.copy()
    pose[:3] = Y_TO_Z.T @ native[:3]
    if frame.header.camera_convention == "arkit":
        pose = pose @ np.diag([1, -1, -1, 1])
    return replace(
        frame,
        header=frame.header.model_copy(update={"camera_to_world": tuple(pose.flatten(order="F"))}),
    )
