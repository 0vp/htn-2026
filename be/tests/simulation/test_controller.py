"""Physics regression tests, including failure paths and measured outcomes."""

import numpy as np
import pytest

pytest.importorskip("mujoco")

from htn_backend.simulation.controller import Controller
from htn_backend.simulation.planning import line_clear, plan
from htn_backend.simulation.world import World


@pytest.mark.parametrize("seed", [0, 11, 17])
def test_powered_wheel_reaches_open_room_target_without_teleports(seed):
    world = World(seed, "open")
    try:
        assert Controller(world).execute("navigate", "blue_block")[0]
        assert world.collisions == 0 and world.path_length > 1
        assert not world.failed
        assert world.stop()
    finally:
        world.close()


def test_unreachable_goal_and_out_of_reach_grasp_fail():
    world = World(layout="blocked")
    controller = Controller(world)
    try:
        initial = world.pose.copy()
        assert not controller.execute("pick", "blue_block")[0]
        assert not controller.execute("navigate", "blue_block")[0]
        assert np.linalg.norm(world.pose[:2] - initial[:2]) < 0.01
        assert not controller.execute("place", "delivery_table")[0]
        assert world.held is None and world.collisions == 0
    finally:
        world.close()


def test_cancellation_stops_base_and_never_reports_arrival():
    world = World()
    initial = world.data.time
    world.callback = lambda: setattr(world, "cancelled", world.data.time - initial > 3)
    try:
        assert not Controller(world).execute("navigate", "blue_block")[0]
        assert world.stop()
        assert world.data.ctrl[world.act["wheel"]] == 0
        assert world.collisions == 0
    finally:
        world.close()


def test_physics_instability_is_not_silently_treated_as_a_reset():
    import mujoco

    world = World()
    try:
        world.data.warning[int(mujoco.mjtWarning.mjWARN_BADQACC)].number = 1
        with pytest.raises(RuntimeError, match="numerical_instability"):
            world.step()
        assert world.failed
        assert not world.stop()
    finally:
        world.close()


def test_inflated_planner_cannot_cut_obstacle_corners():
    start, target, obstacles = (-1.5, 0), (1.5, 0), [(0, 0, 0.4, 0.6)]
    path = plan(start, target, obstacles)
    assert path and len(path) > 1
    assert all(line_clear(a, b, obstacles) for a, b in zip([start, *path[:-1]], path, strict=True))
