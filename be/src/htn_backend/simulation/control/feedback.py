"""Measured robot feedback; never include unobserved scene-object positions."""

import time

import mujoco
import numpy as np


def measure(world, sequence):
    w = world
    joints = ("steering", "wheel", "shoulder", "elbow", "wrist")
    forces = {"left": 0.0, "right": 0.0}
    for contact_index, contact in enumerate(w.data.contact[: w.data.ncon]):
        names = [w.model.geom(int(g)).name for g in (contact.geom1, contact.geom2)]
        force = np.zeros(6)
        mujoco.mj_contactForce(w.model, w.data, contact_index, force)
        for side in forces:
            if any(name.startswith(side + "_segment") for name in names):
                forces[side] += max(0.0, float(force[0]))
    to_room = np.array([[1.0, 0, 0], [0, 0, 1], [0, -1, 0]])
    end_effector = to_room @ w.data.site("grasp").xpos
    return dict(
        sequence=sequence,
        received_at=time.time(),
        simulation_time_s=float(w.data.time),
        execution_domain="simulation",
        source="MuJoCo measured state; ideal encoders/poses/contact forces",
        phase=getattr(w, "phase", "idle"),
        end_effector_position_room_m=end_effector.tolist(),
        coordinate_system="right_handed_y_up_meters",
        commanded_joint_targets={
            n: float(w.data.ctrl[w.act[n]]) for n in ("shoulder", "elbow", "wrist")
        },
        joints={
            name: dict(
                position=float(w.data.joint(name).qpos[0]),
                velocity=float(w.data.joint(name).qvel[0]),
            )
            for name in joints
        },
        base_speed_m_s=float(np.linalg.norm(w.data.joint("base_free").qvel[:2])),
        yaw_rate_rad_s=float(w.data.joint("base_free").qvel[5]),
        tentacle_normal_force_n=forces,
        collision_steps=w.collisions,
        held_object=w.held,
        cancelled=w.cancelled,
        numerical_failure=w.failed,
        controller=getattr(w, "control_feedback", {}),
    )
