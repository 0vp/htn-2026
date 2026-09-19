"""Instance masks in the calibrated image grid."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    mask: np.ndarray
