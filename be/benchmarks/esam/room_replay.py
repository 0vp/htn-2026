"""Replay both mappers through room storage/publication in disposable private databases."""

import argparse
import json
import tempfile
import time
from pathlib import Path

from htn_backend.capture.codec import decode
from htn_backend.inference.client import Detector
from htn_backend.mapping.hydra.client import HydraClient
from htn_backend.perception.esam.fusion import HydraEsam
from htn_backend.processing.room import RoomProcessor
from htn_backend.processing.state import ProcessingState
from htn_backend.storage.database import Store


def replay(paths, output, detector, mapper_factory):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="room-replay-", dir=output) as directory:
        store = Store(Path(directory))
        processor = None
        started = time.perf_counter()
        report = {"mapper": mapper_factory.__name__, "batches": []}
        try:
            code = store.create("Evaluation")["room_id"]
            store.join(code, "replay", "Evaluation capture")
            for path in paths:
                payload = path.read_bytes()
                store.save(code, "replay", decode(payload), payload)
            state = ProcessingState(store)
            processor = RoomProcessor(state, code, detector, mapper_factory=mapper_factory)
            while processor.step():
                status = state.status(code)
                report["batches"].append(status["map"])
                print(
                    json.dumps({"mapper": mapper_factory.__name__, "mapped": status["mapped"]}),
                    flush=True,
                )
            final = state.snapshot(code)
            (output / "mesh.glb").write_bytes(final["mesh"])
            (output / "objects.json").write_text(json.dumps(final["objects"], indent=2))
            report.update(status=state.status(code), objects=len(final["objects"]))
            processor.seal()
            report["checkpoint_objects"] = len(processor.atlas.objects)
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            if processor is not None:
                processor.close()
            store.close()
            report["elapsed_s"] = time.perf_counter() - started
            report["accuracy"] = "Not scored: these captures lack instance ground-truth annotations"
            (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(args.captures.glob("*.bin"))
    if not paths:
        parser.error("No captures found")
    detector = Detector()
    try:
        for factory in (HydraClient, HydraEsam):
            replay(paths, args.output / factory.__name__, detector, factory)
    finally:
        detector.close()


if __name__ == "__main__":
    main()
