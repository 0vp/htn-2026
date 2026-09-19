"""End-to-end task success uses physics, not an action receipt alone."""

import numpy as np
import pytest

pytest.importorskip("mujoco")

from htn_backend.simulation.controller import Controller
from htn_backend.simulation.world import World


def test_contact_verified_delivery_after_position_only_navigation():
    world = World(11, "open")
    controller = Controller(world)
    try:
        original = world.block.copy()
        assert controller.execute("navigate", "blue_block")[0]
        assert controller.execute("pick", "blue_block")[0]
        assert world.grasp_contacts() and world.block[2] > original[2] + 0.1
        assert controller.execute("navigate", "delivery_table")[0]
        assert world.grasp_contacts()
        assert controller.execute("place", "delivery_table")[0]
        table = world.tables["delivery_table"]
        assert abs(world.block[2] - table[2] - 0.035) < 0.015
        assert np.linalg.norm(world.block[:2] - table[:2]) < 0.45
        assert frozenset(("blue_block", "delivery_table")) in world.contacts()
        assert world.held is None and not world.grasp_contacts()
        assert world.collisions == 0 and not world.failed
    finally:
        world.close()
