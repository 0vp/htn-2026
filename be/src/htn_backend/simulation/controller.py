"""Closed-loop navigation and contact-verified manipulation for the test robot."""

import math

import numpy as np

from .planning import line_clear, plan
from .world import angle


class Controller:
    def __init__(self, world):
        self.world = world
        self.failure = None

    def execute(self, skill, object_id):
        w = self.world
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
            return self.pick(object_id)
        if skill == "place":
            return self.place(object_id)
        return False, "unsupported_skill"

    def navigate(self, target, radius=0.65):
        w = self.world
        self.failure = "goal_pose_tolerance_not_reached"
        w.settle_arm(0.55 if w.held else 0.4, 0.05 if w.held else 0, 0.065 if w.held else 0)
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
                velocity = min(0.12, distance * 0.5)
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

    def arm_target(self, position):
        w = self.world
        delta = position[:2] - w.pose[:2]
        heading = math.atan2(delta[1], delta[0])
        if abs(angle(heading - w.pose[2])) > 0.06:
            return None
        reach = float(np.linalg.norm(delta) - 0.14)
        lift = float(position[2] - 0.33 + 0.025)
        if not (0 <= reach <= 0.6 and 0 <= lift <= 0.65):
            return None
        return lift, reach

    def pick(self, object_id):
        w = self.world
        if object_id != "blue_block":
            return False, "object_not_graspable"
        if w.held:
            return False, "gripper_occupied"
        target = self.arm_target(w.block)
        if target is None:
            return False, "target_outside_arm_workspace: navigate to object first"
        lift, reach = target
        initial = w.block.copy()
        # Approach above the object, then descend with uncurled tentacles.
        for command in (
            (lift + 0.13, 0, 0),
            (lift + 0.13, reach, 0),
            (lift, reach, 0),
            (lift, reach, 0.065),
        ):
            if not w.settle_arm(*command):
                return False, "cancelled"
        if not w.grasp_contacts():
            w.settle_arm(lift + 0.13, reach, 0)
            return False, "bilateral_gripper_contact_not_found"
        w.settle_arm(lift + 0.15, reach, 0.065, seconds=2)
        lifted = w.block[2] - initial[2] > 0.10 and w.grasp_contacts()
        if lifted:
            w.held = object_id
        return bool(lifted), (
            "lift_and_bilateral_contact_checked" if lifted else "grasp_lost_or_lift_too_small"
        )

    def place(self, object_id):
        w = self.world
        if not w.held:
            return False, "gripper_empty"
        table = w.tables.get(object_id)
        if table is None:
            return False, "target_is_not_a_support_surface"
        # Place on the reachable near edge of the requested support surface.
        direction = w.pose[:2] - np.array(table[:2])
        direction /= max(np.linalg.norm(direction), 1e-9)
        position = np.array([*(np.array(table[:2]) + direction * 0.28), table[2] + 0.04])
        if np.linalg.norm(position[:2] - w.pose[:2]) > 0.74:
            return False, "surface_unreachable: navigate to support surface first"
        w.settle_arm(0.55, 0.05, 0.065)
        target = self.arm_target(position)
        if target is None:
            return False, "surface_outside_arm_workspace"
        lift, reach = target
        w.settle_arm(lift + 0.15, reach, 0.065)
        w.settle_arm(lift + 0.03, reach, 0.065)
        w.settle_arm(lift + 0.03, reach, 0)
        w.settle_arm(lift + 0.18, reach, 0, seconds=2)
        position = w.block
        supported = (
            abs(position[0] - table[0]) < 0.42
            and abs(position[1] - table[1]) < 0.47
            and abs(position[2] - table[2] - 0.035) < 0.015
        )
        w.held = None
        return bool(supported), (
            "released_object_support_height_checked"
            if supported
            else "released_object_not_stably_supported"
        )
