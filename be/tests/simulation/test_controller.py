"""Physics regression tests, including failure paths and measured outcomes."""

import numpy as np
import pytest

pytest.importorskip("mujoco")

from htn_backend.simulation.controller import Controller
from htn_backend.simulation.planning import line_clear, plan
from htn_backend.simulation.world import World


@pytest.mark.parametrize("seed,layout", [(0, "open"), (11, "detour"), (17, "detour")])
def test_contact_based_delivery_without_teleports(seed, layout):
    world = World(seed, layout)
    controller = Controller(world)
    try:
        initial = world.block.copy()
        assert controller.execute("navigate", "blue_block")[0]
        assert controller.execute("pick", "blue_block")[0]
        assert world.grasp_contacts() and world.block[2] > initial[2] + 0.10
        assert controller.execute("navigate", "delivery_table")[0]
        assert world.grasp_contacts()
        assert controller.execute("place", "delivery_table")[0]
        table = world.tables["delivery_table"]
        assert abs(world.block[2] - table[2] - 0.035) < 0.015
        assert np.linalg.norm(world.block[:2] - table[:2]) < 0.4
        assert world.held is None and not world.grasp_contacts()
        assert world.collisions == 0 and world.path_length > 2
        assert not world.failed
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
        assert np.linalg.norm(world.data.ctrl[:3]) == 0
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
