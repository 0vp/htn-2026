"""Measured control regressions, including perturbed loads and steering reversal."""

import math

import numpy as np
import pytest

pytest.importorskip("mujoco")

from htn_backend.simulation.control.arm import measured, move_hand
from htn_backend.simulation.world import World


@pytest.mark.parametrize("mass_scale", [0.7, 1.3])
def test_measured_endpoint_servo_corrects_load_dependent_error(mass_scale):
    world = World(layout="open")
    try:
        # Fixture perturbation only: controller never reads this parameter.
        for name in ("shoulder", "elbow", "wrist", "palm"):
            world.model.body_mass[world.model.body(name).id] *= mass_scale
            world.model.body_inertia[world.model.body(name).id] *= mass_scale
        import mujoco

        mujoco.mj_setConst(world.model, mujoco.MjData(world.model))
        mujoco.mj_forward(world.model, world.data)
        assert move_hand(world, 0.4, 0.85, 0)[0]
        error = np.linalg.norm(measured(world)[:2] - [0.4, 0.85])
        assert error < 0.01
        assert world.control_feedback["calibration"]["accepted_samples"] > 0
        assert world.collisions == 0
    finally:
        world.close()


def test_equivalent_steering_directions_do_not_chatter_at_ninety_degrees():
    world = World(layout="open")
    try:
        world.data.joint("steering").qpos[0] = 1.45
        signs = []
        for offset in [-0.01, 0.01, -0.02, 0.02]:
            theta = world.pose[2] + math.pi / 2 + offset
            world.drive_world(0.1 * math.cos(theta), 0.1 * math.sin(theta), 0)
            signs.append(np.sign(world.command_speed))
            assert world.command_steering > 1
        assert signs == [1, 1, 1, 1]
    finally:
        world.close()


def test_invalid_calibration_target_cannot_make_successful_motion():
    world = World(layout="open")
    try:
        assert move_hand(world, float("nan"), 0.85, 0) == (False, "invalid_arm_target")
        world.cancelled = True
        assert move_hand(world, 0.4, 0.85, 0) == (False, "cancelled")
    finally:
        world.close()
