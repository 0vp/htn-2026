"""Obstacle-aware route finding: a remembered occupancy grid, inflation, A*, path shortcuts.

The same recipe as ROS 2 Nav2 and most mobile robots: LiDAR hits accumulate in a world-frame
grid (so obstacles stay known after they leave the camera's narrow view), obstacles are inflated
by the robot's radius plus a margin so the robot can be planned as a point, A* finds the
cheapest cell path preferring the middle of free space, and the path is shortened to straight
legs the base can drive. The route is re-planned after every leg from fresh LiDAR.
"""

import heapq
import math

import cv2
import numpy as np

CELL_M = 0.10
SIZE = 400  # 40 m square world window, centred where the grid was created.
ROBOT_RADIUS_M = 0.40  # The base is 80 cm across; the phone sits at its centre.
MARGIN_M = 0.15
UNKNOWN, FREE, OCCUPIED = 0, 1, 2
UNKNOWN_COST = 1.5  # Unseen floor is allowed (the camera sees a narrow wedge) but discouraged.
NEAR_COST = 4.0  # Extra cost per cell that decays with distance from obstacles.


class Grid:
    def __init__(self, origin: tuple[float, float]):
        self.origin = origin
        self.cells = np.full((SIZE, SIZE), UNKNOWN, np.uint8)
        self.hits = np.zeros((SIZE, SIZE), np.uint8)

    def index(self, x: float, z: float) -> tuple[int, int]:
        col = int(round((x - self.origin[0]) / CELL_M)) + SIZE // 2
        row = int(round((z - self.origin[1]) / CELL_M)) + SIZE // 2
        return row, col

    def point(self, row: int, col: int) -> tuple[float, float]:
        return (
            (col - SIZE // 2) * CELL_M + self.origin[0],
            (row - SIZE // 2) * CELL_M + self.origin[1],
        )

    def inside(self, row: int, col: int) -> bool:
        return 0 <= row < SIZE and 0 <= col < SIZE

    def _cells(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        col = np.round((points[:, 0] - self.origin[0]) / CELL_M).astype(int) + SIZE // 2
        row = np.round((points[:, 1] - self.origin[1]) / CELL_M).astype(int) + SIZE // 2
        keep = (row >= 0) & (row < SIZE) & (col >= 0) & (col < SIZE)
        return row[keep], col[keep]

    def integrate(self, floor: np.ndarray, obstacles: np.ndarray) -> None:
        """Fold one LiDAR frame in. Seen floor clears a cell unless it keeps being hit."""
        if len(floor):
            row, col = self._cells(floor)
            self.hits[row, col] = np.maximum(self.hits[row, col], 1) - 1
            clear = self.hits[row, col] == 0
            self.cells[row[clear], col[clear]] = FREE
        if len(obstacles):
            row, col = self._cells(obstacles)
            counts = np.zeros_like(self.hits, dtype=np.uint16)
            np.add.at(counts, (row, col), 1)
            solid = counts >= 3  # A few returns, not one stray point.
            self.hits[solid] = np.minimum(self.hits[solid].astype(int) + 2, 6).astype(np.uint8)
            self.cells[solid] = OCCUPIED

    def costs(self, start: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        """(blocked mask, per-cell cost) with obstacles inflated by the robot's footprint."""
        occupied = (self.cells == OCCUPIED).astype(np.uint8)
        distance = cv2.distanceTransform(1 - occupied, cv2.DIST_L2, 5) * CELL_M
        blocked = distance < ROBOT_RADIUS_M + MARGIN_M
        # The robot may already stand inside an inflated zone (beside a table): let it drive out,
        # but never through cells that are truly within its hull of an obstacle.
        escape = np.zeros_like(occupied)
        cv2.circle(escape, (start[1], start[0]), int(0.6 / CELL_M), 1, -1)
        blocked &= ~(escape.astype(bool) & (distance >= ROBOT_RADIUS_M * 0.75))
        cost = 1.0 + NEAR_COST * np.clip(1.2 - distance, 0, 1.2) / 1.2
        cost[self.cells == UNKNOWN] += UNKNOWN_COST
        return blocked, cost


def astar(blocked, cost, start, goal, limit=60000):
    """8-connected A* over the grid; returns the cell path or None."""
    if blocked[goal]:
        return None
    frontier = [(0.0, start)]
    came, best = {start: None}, {start: 0.0}
    steps = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1)]
    steps += [(-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
    while frontier and limit:
        limit -= 1
        _, current = heapq.heappop(frontier)
        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = came[current]
            return path[::-1]
        for dr, dc, length in steps:
            nxt = (current[0] + dr, current[1] + dc)
            if not (0 <= nxt[0] < SIZE and 0 <= nxt[1] < SIZE) or blocked[nxt]:
                continue
            score = best[current] + length * cost[nxt]
            if score < best.get(nxt, math.inf):
                best[nxt], came[nxt] = score, current
                heuristic = math.hypot(goal[0] - nxt[0], goal[1] - nxt[1])
                heapq.heappush(frontier, (score + heuristic, nxt))
    return None


def visible(blocked, a, b) -> bool:
    count = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) or 1
    rows = np.linspace(a[0], b[0], count + 1).round().astype(int)
    cols = np.linspace(a[1], b[1], count + 1).round().astype(int)
    return not blocked[rows, cols].any()


def shortcut(blocked, path):
    """Keep only the corners: each leg is the longest straight line clear of inflated cells."""
    legs, anchor = [path[0]], 0
    while anchor < len(path) - 1:
        reach = len(path) - 1
        while reach > anchor + 1 and not visible(blocked, path[anchor], path[reach]):
            reach -= 1
        legs.append(path[reach])
        anchor = reach
    return legs


def nearest_free(blocked, goal, start=None, radius_cells=15):
    """Closest drivable cell to a goal that sits on or beside an obstacle (the standoff)."""
    if not blocked[goal]:
        return goal
    rows, cols = np.where(~blocked)
    if not len(rows):
        return None
    distance = np.hypot(rows - goal[0], cols - goal[1])
    if start is not None:  # Among equally near cells, stand on the robot's side of the obstacle.
        distance = distance + 0.3 * np.hypot(rows - start[0], cols - start[1]) * (
            distance <= radius_cells
        )
    nearest = int(distance.argmin())
    near = math.hypot(rows[nearest] - goal[0], cols[nearest] - goal[1]) <= radius_cells
    return (int(rows[nearest]), int(cols[nearest])) if near else None


def plan(grid: Grid, position, target):
    """World-frame waypoints from position to (near) target, or None with a reason."""
    start, goal = grid.index(*position), grid.index(*target)
    if not grid.inside(*goal):
        return None, "the goal is outside the mapped window"
    blocked, cost = grid.costs(start)
    blocked[start] = False
    goal = nearest_free(blocked, goal, start)
    if goal is None:
        return None, "the goal is surrounded by obstacles"
    cells = astar(blocked, cost, start, goal)
    if cells is None:
        return None, "no obstacle-free route was found"
    return [grid.point(*cell) for cell in shortcut(blocked, cells)], None


def draw(grid: Grid, position, heading_deg, waypoints, span_m=8.0) -> bytes:
    """Picture of the remembered grid around the robot with the planned route."""
    half = int(span_m / 2 / CELL_M)
    row, col = grid.index(*position)
    top, left = max(0, row - half), max(0, col - half)
    window = grid.cells[top : row + half, left : col + half]
    colours = np.array([(70, 70, 78), (225, 225, 225), (200, 40, 40)], np.uint8)
    image = cv2.resize(colours[window], None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST)

    def pixel(x, z):
        r, c = grid.index(x, z)
        return int((c - left) * 5), int((r - top) * 5)

    points = [pixel(*position), *(pixel(*w) for w in waypoints or [])]
    for a, b in zip(points, points[1:], strict=False):
        cv2.line(image, a, b, (40, 170, 60), 2)
    for point in points[1:]:
        cv2.circle(image, point, 4, (40, 170, 60), -1)
    cv2.circle(image, points[0], int(ROBOT_RADIUS_M / CELL_M * 5), (255, 210, 0), 2)
    theta = math.radians(heading_deg)
    tip = (int(points[0][0] - math.sin(theta) * 30), int(points[0][1] - math.cos(theta) * 30))
    cv2.line(image, points[0], tip, (255, 210, 0), 2)
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    return encoded.tobytes()
