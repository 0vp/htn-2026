"""Closed-loop navigation and contact-verified manipulation for the test robot."""

import math

import numpy as np

from .control.approach import footprint_clear, rotation
from .control.arm import move_hand
from .control.manipulation import pick, place
from .planning import clear, line_clear, plan
from .world import angle


class Controller:
    def __init__(self, world):
        self.world = world
        self.failure = None

    def execute(self, skill, object_id):
        w = self.world
        w.phase = skill
        if skill == "stop":
            return w.stop(), "base_velocity_checked"
        if w.cancelled:
            return False, "cancelled"
        if skill == "navigate":
            targets = getattr(w, "targets", {**w.tables, "blue_block": w.block})
            target = targets.get(object_id)
            if target is None:
                return False, "target_not_found"
            success = self.navigate(
                np.array(target),
                radius=0
                if object_id.startswith("viewpoint_")
                else (0.8 if object_id == "blue_block" else 1.2),
            )
            return success, "navigation_feedback_checked" if success else self.failure
        if skill == "pick":
            return pick(self, object_id)
        if skill == "place":
            return place(self, object_id)
        return False, "unsupported_skill"

    def navigate(self, target, radius=0.65):
        w = self.world
        self.failure = "goal_pose_tolerance_not_reached"
        if w.held:
            success, detail = move_hand(w, 0.19, 0.88, 1)
            if not success or not w.grasp_contacts():
                self.failure = detail if not success else "grasp_lost"
                return False
        else:
            w.settle_arm(0.4, 0, 0)
        if not clear(w.pose[:2], w.obstacles):
            # Fine manipulation poses use an oriented envelope. Back out until the
            # conservative global planner's circular envelope is valid again.
            w.phase = "retreat_to_navigation_clearance"
            for _ in range(300):
                if clear(w.pose[:2], w.obstacles):
                    w.stop()
                    break
                if w.cancelled or not footprint_clear(w.pose, w.obstacles):
                    self.failure = "retreat_clearance_lost"
                    w.stop()
                    return False
                w.drive_world(*(-rotation(w.pose[2])[:, 0] * 0.07), 0)
                w.step(0.05)
                if w.collisions:
                    self.failure = "retreat_environment_contact"
                    w.stop()
                    return False
            else:
                self.failure = "retreat_not_converged"
                w.stop()
                return False
        candidates = []
        # Try all reachable approach directions; no scene-specific approach point.
        for theta in np.linspace(-math.pi, math.pi, 24, endpoint=False):
            goal = target[:2] + radius * np.array([math.cos(theta), math.sin(theta)])
            path = plan(w.pose[:2], goal, w.obstacles)
            if path:
                length = sum(
                    np.linalg.norm(b - a)
                    for a, b in zip([w.pose[:2], *path[:-1]], path, strict=True)
                )
                candidates.append((float(length), goal, path))
        if not candidates:
            self.failure = "no_collision_free_path_to_reachable_approach"
            return False
        _, goal, path = min(candidates, key=lambda value: value[0])
        for waypoint in path:
            for _ in range(1600):
                if w.cancelled:
                    self.failure = "cancelled"
                    w.stop()
                    return False
                delta = waypoint - w.pose[:2]
                distance = np.linalg.norm(delta)
                if distance < 0.05:
                    break
                error = angle(math.atan2(delta[1], delta[0]) - w.pose[2])
                velocity = min(0.12, max(0.04, distance * 0.5))
                w.control_feedback = dict(
                    position_error_m=float(distance), waypoint=waypoint.tolist()
                )
                direction = delta / distance
                if not line_clear(
                    w.pose[:2], w.pose[:2] + direction * velocity * 0.15, w.obstacles
                ):
                    self.failure = "obstacle_in_local_stopping_path"
                    w.stop()
                    return False
                desired = direction * velocity
                actual = w.data.joint("base_free").qvel[:2]
                lateral = actual - direction * np.dot(actual, direction)
                w.drive_world(*(desired - lateral), np.clip(error * 1.5, -0.5, 0.5))
                w.step()
                if w.collisions or (w.held and not w.grasp_contacts()):
                    self.failure = "robot_environment_contact" if w.collisions else "grasp_lost"
                    if not w.grasp_contacts():
                        w.held = None
                    w.stop()
                    return False
            else:
                self.failure = "navigation_time_budget_exceeded"
                w.stop()
                return False
            w.stop()
        stopped = w.stop()
        if not stopped:
            self.failure = "base_failed_to_settle"
        return bool(stopped and np.linalg.norm(w.pose[:2] - goal) < 0.06)
