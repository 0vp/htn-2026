"""Validate the requested mechanism rather than the retired ideal planar robot."""

import numpy as np
import pytest

pytest.importorskip("mujoco")

import mujoco

from htn_backend.simulation.mechanics.kinematics import arm_ik
from htn_backend.simulation.world import World


def test_one_drive_wheel_four_passive_ball_casters_and_three_arm_joints():
    world = World()
    try:
        model = world.model
        assert model.joint("base_free").type[0] == mujoco.mjtJoint.mjJNT_FREE
        assert set(world.act) == {
            "wheel",
            "steering",
            "shoulder",
            "elbow",
            "wrist",
            "left_curl",
            "right_curl",
        }
        for name in ("caster_fl", "caster_fr", "caster_rl", "caster_rr"):
            joint = model.joint(name)
            assert joint.type[0] == mujoco.mjtJoint.mjJNT_BALL
            assert model.geom(name).type[0] == mujoco.mjtGeom.mjGEOM_SPHERE
            assert not any(model.actuator_trnid[i, 0] == joint.id for i in range(5))
        initial = world.pose.copy()
        # A yaw command alone must not create fictitious skid-steer rotation.
        world.drive_world(0, 0, 1)
        world.step(1)
        assert np.linalg.norm(world.pose - initial) < 0.001
        for _ in range(50):
            world.drive_world(0.12, 0, 0)
            world.step()
        assert world.pose[0] > initial[0] + 0.15
        assert world.stop() and world.collisions == 0
    finally:
        world.close()


def test_tentacles_curl_and_uncurl_with_no_grasp_weld():
    world = World()
    try:
        assert world.model.neq == 0
        assert world.settle_arm(0.4, 0, 0.065)
        curled = sum(world.data.joint(f"left_curl_{i}").qpos[0] for i in range(5))
        assert curled > 1.0
        assert world.settle_arm(0.4, 0, 0, seconds=3)
        uncurled = sum(abs(world.data.joint(f"left_curl_{i}").qpos[0]) for i in range(5))
        assert uncurled < 0.15
        assert world.held is None and world.collisions == 0
    finally:
        world.close()


def test_ik_rejects_unreachable_pose_and_matches_forward_kinematics():
    with pytest.raises(ValueError):
        arm_ik(2, 0.8)
    angles = arm_ik(0.4, 0.75)
    shoulder, elbow, wrist = angles
    assert abs(sum(angles)) < 1e-8
    x = 0.4 * np.cos(shoulder) + 0.35 * np.cos(shoulder + elbow) + 0.1 * np.cos(sum(angles))
    z = 0.4 - 0.4 * np.sin(shoulder) - 0.35 * np.sin(shoulder + elbow) - 0.1
    assert x == pytest.approx(0.4) and z == pytest.approx(0.75)
