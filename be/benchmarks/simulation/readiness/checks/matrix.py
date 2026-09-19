"""Paired controller regressions plus fresh same-template holdouts, not SLAM scores."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from htn_backend.simulation.controller import Controller
from htn_backend.simulation.world import World


def episode(case):
    layout, seed, split = case
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
            ok, reason = controller.execute(skill, target)
            stages.append(dict(skill=skill, target=target, success=bool(ok), reason=reason))
            if not ok:
                break
        complete = len(stages) == 4 and all(s["success"] for s in stages)
        return dict(
            layout=layout,
            seed=seed,
            split=split,
            stages=stages,
            complete=complete,
            collision_steps=world.collisions,
            path_length_m=world.path_length,
            wall_time_s=time.monotonic() - started,
            simulation_time_s=float(world.data.time),
            expected_behavior=bool(
                world.collisions == 0
                and (not stages[0]["success"] if layout == "blocked" else complete)
            ),
        )
    finally:
        world.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [
        (layout, seed, "regression")
        for layout in ("open", "detour", "blocked")
        for seed in range(20, 30)
    ]
    cases += [
        (layout, seed, "holdout") for layout in ("open", "detour") for seed in range(201, 205)
    ]
    source = Path(__file__).resolve().parents[4] / "src/htn_backend/simulation"
    hashes = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*.py"))
    }
    (args.output / "source-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    rows = []
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(episode, case) for case in cases]
        with (args.output / "cases.jsonl").open("w") as output:
            for job in as_completed(jobs):
                row = job.result()
                rows.append(row)
                line = json.dumps(row, allow_nan=False)
                print(line, flush=True)
                output.write(line + "\n")
                output.flush()
    groups = {}
    for split in ("regression", "holdout"):
        for layout in ("open", "detour", "blocked"):
            subset = [r for r in rows if r["split"] == split and r["layout"] == layout]
            if subset:
                groups[f"{split}/{layout}"] = dict(
                    cases=len(subset),
                    deliveries=sum(r["complete"] for r in subset),
                    expected_behavior=sum(r["expected_behavior"] for r in subset),
                    collisions=sum(r["collision_steps"] > 0 for r in subset),
                )
    summary = dict(
        input="ideal poses and static obstacle map",
        groups=groups,
        physical_validation=False,
        public_benchmark=False,
    )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
