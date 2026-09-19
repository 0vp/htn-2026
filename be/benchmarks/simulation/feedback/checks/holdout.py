"""Fresh pose-offset/load probes; not a public benchmark or unseen-room test."""

import json
import time
from pathlib import Path

import mujoco

from htn_backend.simulation.controller import Controller
from htn_backend.simulation.world import World

rows = []
for seed, scale in [(101, 0.8), (102, 1.2), (103, 0.8), (104, 1.2)]:
    world = World(seed, "open")
    try:
        for name in ("shoulder", "elbow", "wrist", "palm"):
            ident = world.model.body(name).id
            world.model.body_mass[ident] *= scale
            world.model.body_inertia[ident] *= scale
        mujoco.mj_setConst(world.model, mujoco.MjData(world.model))
        mujoco.mj_forward(world.model, world.data)
        controller = Controller(world)
        stages = []
        started = time.monotonic()
        for skill, target in [
            ("navigate", "blue_block"),
            ("pick", "blue_block"),
            ("navigate", "delivery_table"),
            ("place", "delivery_table"),
        ]:
            success, reason = controller.execute(skill, target)
            stages.append(dict(skill=skill, success=bool(success), reason=reason))
            if not success:
                break
        row = dict(
            seed=seed,
            arm_mass_inertia_scale=scale,
            stages=stages,
            collision_steps=world.collisions,
            wall_time_s=time.monotonic() - started,
            complete=len(stages) == 4 and all(s["success"] for s in stages),
        )
        rows.append(row)
        print(json.dumps(row), flush=True)
    finally:
        world.close()
Path("/tmp/feedback-holdout.json").write_text(json.dumps(rows, indent=2) + "\n")
