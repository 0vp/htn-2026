"""Simulator motor guard independent of agent reasoning and skill loops.

Constant measured-twist projection is a conservative short-horizon check, not
an identified dynamics model or a physical collision-safety certification.
"""

import numpy as np

from .approach import footprint_clear


class MotionStopped(RuntimeError):
    """A motor command was vetoed; callers must report failure, not arrival."""


def stopping_path_clear(pose, velocity, yaw_rate, obstacles):
    values = np.r_[pose, velocity, yaw_rate]
    if not np.isfinite(values).all():
        return False
    speed = float(np.linalg.norm(velocity))
    # Assumed simulator deceleration; must be measured for a physical base.
    horizon = 0.10 + speed / 0.5
    for dt in np.linspace(0, horizon, 6):
        predicted = [*(np.asarray(pose[:2]) + np.asarray(velocity) * dt), pose[2] + yaw_rate * dt]
        if not footprint_clear(predicted, obstacles):
            return False
    return True


def check(world):
    w = world
    if abs(w.data.ctrl[w.act["wheel"]]) < 1e-9:
        return
    reason = None
    if w.cancelled:
        reason = "cancelled"
    elif w.data.time > w.command_deadline:
        reason = "motor_command_expired"
    elif not stopping_path_clear(
        w.pose,
        w.data.joint("base_free").qvel[:2],
        w.data.joint("base_free").qvel[5],
        w.obstacles,
    ):
        reason = "predicted_footprint_collision"
    if reason:
        w.data.ctrl[w.act["wheel"]] = 0
        w.command_speed = 0.0
        w.safety_stop = reason
        raise MotionStopped(reason)
