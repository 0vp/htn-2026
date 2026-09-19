"""Footprint-inflated A* with collision-checked path simplification."""

import heapq
import math

import numpy as np

RADIUS = 0.32  # Includes base, wheels and clearance. Stow arm before navigating.
RESOLUTION = 0.1


def clear(point, obstacles, radius=RADIUS):
    x, y = point
    if abs(x) > 3 - radius or abs(y) > 3 - radius:
        return False
    return all(
        math.hypot(max(abs(x - ox) - sx, 0), max(abs(y - oy) - sy, 0)) > radius
        for ox, oy, sx, sy in obstacles
    )


def line_clear(start, end, obstacles):
    count = max(2, int(np.linalg.norm(np.array(end) - start) / 0.025) + 2)
    return all(clear(point, obstacles) for point in np.linspace(start, end, count))


def plan(start, goal, obstacles):
    if not clear(start, obstacles) or not clear(goal, obstacles):
        return None
    if line_clear(start, goal, obstacles):
        return [np.array(goal)]

    def key(point):
        return tuple(round(float(x) / RESOLUTION) for x in point)

    source, target = key(start), key(goal)

    def point(node):
        return np.array(node) * RESOLUTION

    queue, costs, parents = [(0.0, source)], {source: 0.0}, {}
    while queue:
        _, node = heapq.heappop(queue)
        if node == target:
            path = [np.array(goal)]
            while node != source:
                path.append(point(node))
                node = parents[node]
            path.append(np.array(start))
            path.reverse()
            result, index = [], 0
            while index < len(path) - 1:
                far = index + 1
                for candidate in range(far + 1, len(path)):
                    if line_clear(path[index], path[candidate], obstacles):
                        far = candidate
                result.append(path[far])
                index = far
            return result
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nxt = node[0] + dx, node[1] + dy
            cost = costs[node] + math.hypot(dx, dy)
            if cost >= costs.get(nxt, float("inf")):
                continue
            if not line_clear(point(node), point(nxt), obstacles):
                continue
            parents[nxt], costs[nxt] = node, cost
            heapq.heappush(queue, (cost + math.dist(nxt, target), nxt))
    return None
