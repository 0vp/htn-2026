"""Unseen rigid-block size, mass and yaw probes; fixture changes precede actions."""

import json
import math
from pathlib import Path

import mujoco
import numpy as np

from htn_backend.simulation.controller import Controller
from htn_backend.simulation.world import World


def main():
    rows = []
    for seed, half_size, mass, yaw in (
        (401, 0.03, 0.04, 0),
        (402, 0.04, 0.12, 0),
        (403, 0.035, 0.08, math.pi / 4),
        (404, 0.035, 0.16, math.pi / 6),
    ):
        world = World(seed, "open")
        try:
            body = world.model.body("blue_block").id
            world.model.geom("blue_block").size[:] = half_size
            world.model.body_mass[body] = mass
            world.model.body_inertia[body] = mass * (2 * half_size) ** 2 / 6
            mujoco.mj_setConst(world.model, mujoco.MjData(world.model))
            joint = world.model.body_jntadr[body]
            address = world.model.jnt_qposadr[joint]
            world.data.qpos[address + 2] = world.tables["source_table"][2] + half_size + 0.001
            world.data.qpos[address + 3 : address + 7] = [
                math.cos(yaw / 2),
                0,
                0,
                math.sin(yaw / 2),
            ]
            mujoco.mj_forward(world.model, world.data)
            world.step(0.5)
            controller = Controller(world)
            stages = []
            for skill, target in [
                ("navigate", "blue_block"),
                ("pick", "blue_block"),
                ("navigate", "delivery_table"),
                ("place", "delivery_table"),
            ]:
                ok, reason = controller.execute(skill, target)
                stages.append(dict(skill=skill, success=bool(ok), reason=reason))
                if not ok:
                    break
            row = dict(
                seed=seed,
                block_half_size_m=half_size,
                mass_kg=mass,
                yaw_rad=yaw,
                stages=stages,
                collision_steps=world.collisions,
                final_position=world.block.tolist(),
                final_speed=float(np.linalg.norm(world.data.body("blue_block").cvel)),
                complete=len(stages) == 4 and all(s["success"] for s in stages),
            )
            rows.append(row)
            print(json.dumps(row), flush=True)
        finally:
            world.close()
    Path("/tmp/readiness-payloads.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
