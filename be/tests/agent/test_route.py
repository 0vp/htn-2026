"""go_to finds its way around obstacles it only discovers on the way (simulated room)."""

import math
from types import SimpleNamespace

import numpy as np

from htn_backend.agent.embodied import planner
from htn_backend.agent.embodied.navigator import Navigator


class Room:
    """A robot pose plus wall points; LiDAR sees a 60 degree wedge out to 4 m."""

    def __init__(self, walls):
        self.walls, self.position, self.heading, self.sequence = walls, [0.0, 0.0], 0.0, 0
        self.closest = math.inf

    def sense(self):
        self.sequence += 1
        forward = np.array(
            [-math.sin(math.radians(self.heading)), -math.cos(math.radians(self.heading))]
        )

        def seen(points):
            offset = points - np.array(self.position)
            distance = np.linalg.norm(offset, axis=1)
            along = offset @ forward
            angle = np.degrees(np.arccos(np.clip(along / np.maximum(distance, 1e-6), -1, 1)))
            return points[(distance < 4.0) & (distance > 0.2) & (angle < 30)]

        gx, gz = np.meshgrid(np.arange(-6, 6, 0.07), np.arange(-9, 3, 0.07))
        floor = seen(np.stack([gx.ravel(), gz.ravel()], 1))
        walls = seen(self.walls)
        ahead = [
            float(o @ forward)
            for o in walls - np.array(self.position)
            if abs(forward[0] * o[1] - forward[1] * o[0]) < 0.52 and o @ forward > 0.1
        ]
        return SimpleNamespace(
            sequence=self.sequence,
            age_s=0.1,
            tracking="normal",
            fresh=True,
            heading_deg=self.heading,
            position=tuple(self.position),
            clear_ahead_m=min(ahead, default=4.0),
            floor_world=floor,
            obstacles_world=np.repeat(walls, 4, axis=0),
        )


class FakeNavigator(Navigator):
    def __init__(self, room):
        self.room, self.grid, self.last_position = room, None, None
        self.senses = SimpleNamespace(read=lambda render=True: room.sense())

    def turn(self, degrees):
        self.room.heading = (self.room.heading + degrees + 180) % 360 - 180
        return dict(moved=True, measured=abs(degrees))

    def forward(self, metres, start):
        step = min(metres, max(0.0, start.clear_ahead_m - 0.65))
        heading = math.radians(self.room.heading)
        for _ in range(int(step / 0.05)):
            self.room.position[0] -= math.sin(heading) * 0.05
            self.room.position[1] -= math.cos(heading) * 0.05
            gap = np.linalg.norm(self.room.walls - np.array(self.room.position), axis=1).min()
            self.room.closest = min(self.room.closest, gap)
        return dict(
            moved=step > 0.05,
            measured=round(step, 2),
            stopped_by=None if step >= metres - 0.06 else "obstacle ahead",
        )


def wall(x0, x1, z):
    xs = np.arange(x0, x1, 0.03)
    return np.stack([xs, np.full_like(xs, z)], 1)


def test_route_goes_through_the_gap_without_touching_anything(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    # A wall 3 m ahead spanning the room, with a 1.4 m doorway off to the right.
    room = Room(np.concatenate([wall(-5, 1.2, -3.0), wall(2.6, 5, -3.0)]))
    result = FakeNavigator(room).go_to((0.0, -6.0))
    assert result["arrived"], result
    assert result["distance_left_m"] <= 0.5
    assert room.closest >= planner.ROBOT_RADIUS_M  # The 80 cm hull never touched the wall.
    assert result["travelled_m"] > 6.5  # It detoured; the straight line is blocked.


def test_route_reports_when_the_way_is_sealed(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    box = np.concatenate(
        [
            wall(-2, 2, -2.0),
            wall(-2, 2, 2.0),
            wall(-2, 2, -2.0)[:, ::-1] * [[1, 1]],
        ]
    )
    sides = np.concatenate(
        [np.stack([np.full(134, x), np.arange(-2, 2.02, 0.03)], 1) for x in (-2.0, 2.0)]
    )
    room = Room(np.concatenate([box, sides]))
    navigator = FakeNavigator(room)
    for heading in range(0, 360, 45):  # Look around first, as a scan would.
        room.heading = heading
        navigator.remember(room.sense())
    result = navigator.go_to((0.0, -6.0))
    assert not result["arrived"] and result["stopped_by"]
    assert room.closest >= planner.ROBOT_RADIUS_M
