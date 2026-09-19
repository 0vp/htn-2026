"""Independent motor stopping and clearance-recovery regressions."""

import numpy as np
import pytest

pytest.importorskip("mujoco")

from htn_backend.simulation.control.approach import footprint_clear
from htn_backend.simulation.control.recovery import escape_path
from htn_backend.simulation.control.safety import MotionStopped, stopping_path_clear
from htn_backend.simulation.planning import PLANNING_RADIUS, clear, line_clear, plan
from htn_backend.simulation.world import World


def test_motor_command_expires_without_agent_or_controller_refresh():
    world = World(layout="open")
    try:
        world.drive_world(0.1, 0, 0)
        with pytest.raises(MotionStopped, match="motor_command_expired"):
            world.step(1)
        assert world.data.ctrl[world.act["wheel"]] == 0
        assert world.stop()
        assert world.collisions == 0
    finally:
        world.close()


def test_measured_velocity_not_requested_direction_drives_collision_prediction():
    obstacle = [(0.65, 0, 0.1, 0.1)]
    assert footprint_clear([0, 0, 0], obstacle)
    assert stopping_path_clear([0, 0, 0], [-0.25, 0], 0, obstacle)
    assert not stopping_path_clear([0, 0, 0], [0.25, 0], 0, obstacle)
    assert not stopping_path_clear([0, 0, 0], [np.nan, 0], 0, [])


def test_recovery_can_leave_narrow_gap_without_reversing_into_neighbor():
    obstacles = [(1.467, 0.525, 0.45, 0.5), (-1.35, 1.3, 0.45, 0.5), (0, -0.35, 0.38, 0.48)]
    pose = np.array([0.551, 0.555, -0.06])
    assert not clear(pose[:2], obstacles, PLANNING_RADIUS)
    path = escape_path(pose, obstacles)
    assert path and clear(path[-1], obstacles, PLANNING_RADIUS)
    assert all(
        footprint_clear([*point, pose[2]], obstacles)
        for a, b in zip([pose[:2], *path[:-1]], path, strict=True)
        for point in np.linspace(a, b, 20)
    )
    assert not footprint_clear([-1, 0.555, -0.06], obstacles)


def test_exact_grid_endpoint_connections_keep_tracking_margin():
    obstacles = [(0, 0, 0.4, 0.6)]
    start, target = [-1.463, -0.021], [1.419, 0.043]
    path = plan(start, target, obstacles)
    assert path
    assert all(
        line_clear(a, b, obstacles, PLANNING_RADIUS)
        for a, b in zip([start, *path[:-1]], path, strict=True)
    )


def test_local_guard_stops_toward_table_without_an_agent():
    world = World(layout="open")
    try:
        target = np.asarray(world.tables["source_table"][:2])
        for _ in range(1400):
            direction = target - world.pose[:2]
            direction /= np.linalg.norm(direction)
            world.drive_world(*(direction * 0.12), 0)
            try:
                world.step(0.05)
            except MotionStopped as error:
                assert str(error) == "predicted_footprint_collision"
                break
        else:
            pytest.fail("Expected obstacle stop before reaching the table")
        assert world.data.ctrl[world.act["wheel"]] == 0
        assert world.stop() and world.collisions == 0
    finally:
        world.close()
