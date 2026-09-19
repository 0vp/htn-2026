"""Approximate shoulder/elbow/wrist IK for assumed link lengths, in meters."""

import math

import numpy as np


def arm_ik(reach, grasp_height, shoulder_height=0.4):
    # Wrist keeps the palm horizontal; the grasp site is 10 cm below the palm.
    x, z = reach - 0.1, grasp_height + 0.1 - shoulder_height
    cosine = (x * x + z * z - 0.4**2 - 0.35**2) / (2 * 0.4 * 0.35)
    if not -1 <= cosine <= 1:
        raise ValueError("arm_target_outside_reach")
    elbow = math.acos(cosine)
    shoulder = math.atan2(-z, x) - math.atan2(0.35 * math.sin(elbow), 0.4 + 0.35 * math.cos(elbow))
    wrist = -shoulder - elbow
    if not (-2.5 <= shoulder <= 1.5 and -2.6 <= elbow <= 2.6 and -2.6 <= wrist <= 2.6):
        raise ValueError("arm_joint_limit")
    return np.array([shoulder, elbow, wrist])
