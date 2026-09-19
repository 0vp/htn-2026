"""Repeatable controller benchmark and real Codex-to-simulator evaluation."""

import argparse
import asyncio
import io
import json
import shutil
import socket
import threading
import time
from pathlib import Path

import uvicorn
from PIL import Image

from ..agent.run import run
from .controller import Controller
from .service import ROOM, create_app
from .world import World

TASK = (
    "Explore this room to find the blue block. Start from the robot camera and observed scene. "
    "Use up to four navigation actions to available viewpoints; observe after each action. "
    "Reconsider a route if motion fails. Report what you actually saw, where you could not "
    "look, and whether you can safely pick the block. Do not assume an unseen object is absent."
)


def matrix():
    rows = []
    for layout in ("open", "detour", "blocked"):
        for seed in range(20, 30):
            world = World(seed, layout)
            controller = Controller(world)
            started = time.monotonic()
            stages = []
            try:
                for skill, target in (
                    ("navigate", "blue_block"),
                    ("pick", "blue_block"),
                    ("navigate", "delivery_table"),
                    ("place", "delivery_table"),
                ):
                    try:
                        success, reason = controller.execute(skill, target)
                    except ValueError as error:
                        success, reason = False, str(error)
                    stages.append(
                        dict(skill=skill, target=target, success=bool(success), reason=reason)
                    )
                    if not success:
                        break
                completed = len(stages) == 4 and all(s["success"] for s in stages)
                expected = not stages[0]["success"] if layout == "blocked" else completed
                rows.append(
                    dict(
                        seed=seed,
                        layout=layout,
                        task_completed=completed,
                        expected_behavior=bool(expected and world.collisions == 0),
                        stages=stages,
                        collision_steps=world.collisions,
                        path_length_m=world.path_length,
                        simulation_time_s=float(world.data.time),
                        wall_time_s=time.monotonic() - started,
                    )
                )
            finally:
                world.close()
    return dict(
        engine="MuJoCo 3.3.7",
        robot="one powered steering wheel, four passive ball casters, 3R arm, twin tentacles",
        input="oracle object poses and static obstacles",
        benchmark="procedural regression suite, not a public robotics leaderboard",
        expected_behavior_rate=sum(r["expected_behavior"] for r in rows) / len(rows),
        delivery_success_rate=sum(r["task_completed"] for r in rows if r["layout"] != "blocked")
        / 20,
        rows=rows,
        limitations=[
            "Uncalibrated assumed geometry, masses, motor limits and contact friction",
            "Single steering contact does not independently control chassis yaw",
            "Manipulation validates only the simulated rigid block, not physical tentacles",
            "Single small rigid block and tuned contact parameters",
            "Static obstacles, perfect localization and object identities",
            "Not a perception, SLAM, physical hardware or model fine-tuning result",
        ],
    )


def agent(output, seed=17, layout="detour", command=TASK):
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("Official Codex CLI required; authenticate it before running")
    app = create_app(seed, layout)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if not worker.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Simulation server failed to start")
            time.sleep(0.02)
        started = time.monotonic()
        # Direct call intentionally excludes physical Motion/RobotLink, even if host env sets them.
        agent_error = None
        try:
            answer = asyncio.run(
                run(ROOM, command, f"http://127.0.0.1:{port}", binary, motion=None)
            )
        except (RuntimeError, TimeoutError) as error:
            # Preserve failed/partial episodes as evidence, including model timeouts.
            agent_error, answer = type(error).__name__, ""
            app.state.sim.world.cancelled = True
            app.state.sim.executor.submit(lambda: None).result(timeout=30)
        sim = app.state.sim
        with sim.lock:
            receipts = list(sim.receipts.values())
            snapshot = sim.scene()
            images = list(sim.frames)
        result = dict(
            model="gpt-6-astra",
            seed=seed,
            layout=layout,
            command=command,
            answer=answer,
            agent_error=agent_error,
            wall_time_s=time.monotonic() - started,
            receipts=receipts,
            scene=snapshot,
            physical_hardware_connected=False,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, allow_nan=False))
        frames = [Image.open(io.BytesIO(data)).convert("RGB") for data in images]
        frames[-1].save(output.with_suffix(".png"))
        frames[0].save(
            output.with_suffix(".gif"), save_all=True, append_images=frames[1:], duration=80, loop=0
        )
        return result
    finally:
        server.should_exit = True
        worker.join(timeout=30)
        listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent", action="store_true", help="Run real Astra instead of controller suite"
    )
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--layout", choices=["open", "detour", "blocked"], default="detour")
    parser.add_argument("--command", default=TASK)
    parser.add_argument("--output", type=Path, default=Path("/tmp/htn-simulation-result.json"))
    args = parser.parse_args()
    if args.agent:
        result = agent(args.output, args.seed, args.layout, args.command)
        print(f"Recorded {len(result['receipts'])} action receipts at {args.output}")
        if result["agent_error"]:
            raise SystemExit(f"Agent evaluation failed: {result['agent_error']}")
    else:
        result = matrix()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False))
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
