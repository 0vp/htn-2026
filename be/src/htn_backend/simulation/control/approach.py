"""Collision-aware approach corridors and closed-loop target-relative alignment."""

import math

import numpy as np

from ..planning import plan


def rotation(yaw):
    return np.array([[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]])


def footprint_clear(pose, obstacles):
    # Conservative planar envelope for this hardware, including stowed arm/casters.
    if not np.isfinite(pose).all():
        return False
    center, basis = np.asarray(pose[:2]), rotation(pose[2])
    if np.any(np.abs(center) > 2.5):
        return False
    half = np.array([0.255, 0.245])
    wheel = center + basis[:, 0] * 0.34
    for ox, oy, sx, sy in obstacles:
        other = np.array([ox, oy])
        extent = np.array([sx, sy]) + 0.015
        axes = [*np.eye(2), basis[:, 0], basis[:, 1]]
        separated = any(
            abs(np.dot(other - center, axis))
            > np.abs(basis.T @ axis) @ half + np.abs(axis) @ extent
            for axis in axes
        )
        distance = np.linalg.norm(np.maximum(np.abs(wheel - other) - extent, 0))
        if not separated or distance < 0.105:
            return False
    return True


def relative_target(world, target):
    return rotation(world.pose[2]).T @ (np.asarray(target[:2]) - world.pose[:2])


def approach_candidates(w, target, corridors, headings):
    candidates = []
    for heading in np.linspace(-math.pi, math.pi, headings, endpoint=False):
        forward = np.array([math.cos(heading), math.sin(heading)])
        goal = target[:2] - 0.64 * forward
        if not footprint_clear([*goal, heading], w.obstacles):
            continue
        for corridor in corridors:
            stage = target[:2] - (0.64 + corridor) * forward
            if not all(
                footprint_clear([*p, heading], w.obstacles) for p in np.linspace(stage, goal, 40)
            ):
                continue
            path = plan(w.pose[:2], stage, w.obstacles)
            if not path:
                continue
            length = sum(
                np.linalg.norm(b - a) for a, b in zip([w.pose[:2], *path[:-1]], path, strict=True)
            )
            candidates.append((float(length + corridor), stage, forward))
    return candidates


def approach(controller, target):
    w = controller.world
    target = np.asarray(target)
    local = relative_target(w, target)
    goal = target[:2] - 0.64 * rotation(w.pose[2])[:, 0]
    if (
        0.4 < local[0] < 1.2
        and abs(local[1]) < 0.4
        and all(
            footprint_clear([*p, w.pose[2]], w.obstacles) for p in np.linspace(w.pose[:2], goal, 20)
        )
    ):
        return align(controller, target)
    candidates = approach_candidates(w, target, (1.2, 1.6, 0.8, 0.6, 2.0, 2.4, 2.8), 16)
    if not candidates:
        candidates = approach_candidates(w, target, np.arange(0.8, 3.21, 0.1), 16)
    if not candidates:
        candidates = approach_candidates(w, target, np.arange(0.8, 3.21, 0.1), 64)
    if not candidates:
        return False, "no_collision_free_arm_approach"
    _, stage, forward = min(candidates, key=lambda value: value[0])
    w.phase = "approach_staging"
    if not controller.navigate(np.array([*stage, target[2]]), radius=0):
        return False, controller.failure
    w.phase = "approach_corridor"
    # Straight run-in encourages heading alignment before precision placement.
    pregoal = target[:2] - 0.83 * forward
    initial_collisions = w.collisions
    for _ in range(1600):
        delta = pregoal - w.pose[:2]
        if np.linalg.norm(delta) < 0.04:
            break
        if w.cancelled or not footprint_clear(w.pose, w.obstacles):
            w.stop()
            return False, "cancelled" if w.cancelled else "approach_clearance_lost"
        direction = delta / max(np.linalg.norm(delta), 1e-9)
        desired = direction * min(0.1, max(0.04, np.linalg.norm(delta) * 0.5))
        actual = w.data.joint("base_free").qvel[:2]
        w.drive_world(*(desired - (actual - direction * np.dot(actual, direction))), 0)
        w.step(0.1)
        if w.collisions > initial_collisions:
            w.stop()
            return False, "approach_environment_contact"
    else:
        w.stop()
        return False, "approach_corridor_timeout"
    w.stop()
    return align(controller, target)


def align(controller, target):
    w = controller.world
    initial_collisions = w.collisions
    w.phase = "target_relative_alignment"
    integral, previous = np.zeros(2), np.zeros(2)
    for _ in range(600):
        error = relative_target(w, target) - [0.64, 0]
        w.control_feedback = dict(
            target_relative_error_m=error.tolist(), position_error_m=float(np.linalg.norm(error))
        )
        if abs(error[0]) < 0.014 and abs(error[1]) < 0.009:
            w.stop()
            error = relative_target(w, target) - [0.64, 0]
            if abs(error[0]) < 0.02 and abs(error[1]) < 0.012:
                return True, "arm_approach_pose_measured"
        if w.cancelled or not footprint_clear(w.pose, w.obstacles):
            w.stop()
            return False, "cancelled" if w.cancelled else "alignment_clearance_lost"
        integral[error * previous < 0] = 0
        integral = np.clip(integral + error * 0.1, -0.5, 0.5)
        local = np.clip(error * [0.7, 0.5] + integral * 0.08, -0.07, 0.07)
        w.drive_world(*(rotation(w.pose[2]) @ local), 0)
        w.step(0.1)
        previous = error
        if w.collisions > initial_collisions:
            w.stop()
            return False, "alignment_environment_contact"
    w.stop()
    return False, "alignment_not_converged"
