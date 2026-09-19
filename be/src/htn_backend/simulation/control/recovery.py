"""Recover navigation clearance using the measured oriented footprint.

A short local lattice finds an escape from a valid precision manipulation pose.
Heading is not independently actuated: replan if measured rotation invalidates
that route, and fail closed rather than assuming the base can turn in place.
"""

import heapq
import math

import numpy as np

from ..planning import PLANNING_RADIUS, clear
from .approach import footprint_clear


def escape_path(pose, obstacles):
    origin = np.asarray(pose[:2])
    yaw = pose[2]
    step = 0.06
    queue, costs, parents = [(0.0, (0, 0))], {(0, 0): 0.0}, {}
    for _ in range(4000):
        if not queue:
            return None
        cost, node = heapq.heappop(queue)
        if cost > costs[node]:
            continue
        point = origin + np.asarray(node) * step
        if clear(point, obstacles, PLANNING_RADIUS + 0.04):
            path = [point]
            while node != (0, 0):
                node = parents[node]
                path.append(origin + np.asarray(node) * step)
            path.reverse()
            # Keep bends; remove only collinear intermediate grid points.
            return [
                p
                for i, p in enumerate(path[1:], 1)
                if i == len(path) - 1 or not np.allclose(p - path[i - 1], path[i + 1] - p)
            ]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nxt = node[0] + dx, node[1] + dy
            candidate = origin + np.asarray(nxt) * step
            value = cost + math.hypot(dx, dy)
            if value >= costs.get(nxt, float("inf")):
                continue
            if np.linalg.norm(candidate - origin) > 2:
                continue
            if not all(
                footprint_clear([*p, yaw], obstacles) for p in np.linspace(point, candidate, 4)
            ):
                continue
            parents[nxt], costs[nxt] = node, value
            heapq.heappush(queue, (value, nxt))
    return None


def recover(controller):
    w = controller.world
    if clear(w.pose[:2], w.obstacles, PLANNING_RADIUS):
        return True
    w.phase = "retreat_to_navigation_clearance"
    path = escape_path(w.pose, w.obstacles)
    if not path:
        controller.failure = "no_clearance_recovery_path"
        return False
    for waypoint in path:
        for _ in range(600):
            if clear(w.pose[:2], w.obstacles, PLANNING_RADIUS):
                if w.stop() and clear(w.pose[:2], w.obstacles, PLANNING_RADIUS):
                    return True
            delta = waypoint - w.pose[:2]
            distance = np.linalg.norm(delta)
            if distance < 0.04:
                break
            if w.cancelled or not footprint_clear(w.pose, w.obstacles):
                controller.failure = "cancelled" if w.cancelled else "retreat_clearance_lost"
                w.stop()
                return False
            direction = delta / distance
            desired = direction * 0.08
            actual = w.data.joint("base_free").qvel[:2]
            w.drive_world(*(desired - (actual - direction * np.dot(actual, direction))), 0)
            w.step(0.05)
            if w.collisions or (w.held and not w.grasp_contacts()):
                controller.failure = "retreat_environment_contact" if w.collisions else "grasp_lost"
                w.stop()
                return False
        else:
            controller.failure = "retreat_not_converged"
            w.stop()
            return False
        w.stop()
    success = clear(w.pose[:2], w.obstacles, PLANNING_RADIUS)
    if not success:
        controller.failure = "retreat_clearance_not_reached"
    return success
