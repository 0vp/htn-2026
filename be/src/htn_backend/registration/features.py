"""Calibrated GPU feature keyframes in metric world coordinates."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Keyframe:
    frame_id: int
    pose: np.ndarray
    points: np.ndarray
    descriptors: np.ndarray
    cloud: np.ndarray
