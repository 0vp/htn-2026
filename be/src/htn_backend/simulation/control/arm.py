"""Measured Cartesian endpoint servo with online local Jacobian correction."""

import math

import numpy as np

from .calibration import OnlineJacobian

JOINTS = ("shoulder", "elbow", "wrist")


def nominal(q):
    angles = np.cumsum(q)
    lengths = np.array([0.4, 0.35, 0.1])
    phi = angles[-1]
    return np.array(
        [
            lengths @ np.cos(angles) - 0.1 * math.sin(phi),
            -lengths @ np.sin(angles) - 0.1 * math.cos(phi),
            phi,
        ]
    )


def measured(w):
    yaw = w.pose[2]
    forward = np.array([math.cos(yaw), math.sin(yaw)])
    site = w.data.site("grasp").xpos
    palm_forward = w.data.body("palm").xmat.reshape(3, 3)[:, 0]
    pitch = math.atan2(-palm_forward[2], np.dot(palm_forward[:2], forward))
    return np.array([np.dot(site[:2] - w.pose[:2], forward), site[2], pitch])


def move_hand(w, reach, height, curl, seconds=4):
    if not np.isfinite([reach, height, curl, seconds]).all() or not 0 <= curl <= 1 or seconds <= 0:
        return False, "invalid_arm_target"
    start = measured(w)
    target = np.array([reach, height, 0.0])
    ids = [w.act[n] for n in JOINTS]
    q = np.array([w.data.joint(n).qpos[0] for n in JOINTS])
    jacobian = np.column_stack(
        [(nominal(q + np.eye(3)[i] * 1e-4) - nominal(q)) / 1e-4 for i in range(3)]
    )
    calibration = OnlineJacobian(jacobian)
    previous_q, previous_measurement = q, start
    initial_collisions = w.collisions
    steps = max(1, int(np.linalg.norm((target - start)[:2]) / 0.015) + 1)
    for waypoint in np.linspace(start, target, steps + 1)[1:]:
        for _ in range(round(seconds / 0.05)):
            if w.cancelled:
                return False, "cancelled"
            actual = measured(w)
            error = waypoint - actual
            q = np.array([w.data.joint(n).qpos[0] for n in JOINTS])
            if not w.grasp_contacts():
                calibration.update(q - previous_q, actual - previous_measurement)
            previous_q, previous_measurement = q.copy(), actual.copy()
            w.control_feedback = dict(
                position_error_m=float(np.linalg.norm(error[:2])),
                pitch_error_rad=float(error[2]),
                calibration=calibration.report(),
            )
            if np.linalg.norm(error[:2]) < 0.003 and abs(error[2]) < 0.025:
                break
            increment = np.clip(calibration.correction(error) * 0.55, -0.025, 0.025)
            w.data.ctrl[ids] = np.clip(
                w.data.ctrl[ids] + increment, [-2.5, -2.6, -2.6], [1.5, 2.6, 2.6]
            )
            w.data.ctrl[w.act["wheel"]] = 0
            w.step()
            if w.collisions > initial_collisions:
                return False, "arm_environment_contact"
        else:
            return False, "endpoint_servo_not_converged"
    # Curl after reaching the pose, so the endpoint controller cannot hide a contact failure.
    for _ in range(60):
        error = target - measured(w)
        increment = np.clip(calibration.correction(error) * 0.3, -0.015, 0.015)
        w.data.ctrl[ids] = np.clip(
            w.data.ctrl[ids] + increment, [-2.5, -2.6, -2.6], [1.5, 2.6, 2.6]
        )
        for name in ("left_curl", "right_curl"):
            i = w.act[name]
            w.data.ctrl[i] += np.clip(curl * 3.6 - w.data.ctrl[i], -0.06, 0.06)
        w.step()
        if w.cancelled or w.collisions > initial_collisions:
            return False, "cancelled" if w.cancelled else "arm_environment_contact"
    error = target - measured(w)
    w.control_feedback = dict(
        position_error_m=float(np.linalg.norm(error[:2])),
        pitch_error_rad=float(error[2]),
        calibration=calibration.report(),
    )
    reached = np.linalg.norm(error[:2]) < 0.01 and abs(error[2]) < 0.05
    return bool(reached), "measured_endpoint_reached" if reached else "endpoint_drift_after_contact"
