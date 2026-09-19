"""Run the candidate against retained calibrated captures without publishing a room."""

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ...capture.codec import read_frame
from ...inference.client import Detector
from ...mapping.objects.confirmation import ObjectConfirmation
from ...mapping.objects.lifecycle import ObjectLifecycle
from ...mapping.objects.orientation import AxialOrientation
from .client import EsamClient
from .runtime import CHECKPOINT_SHA256, REVISION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(args.captures.glob("*.bin"))
    if not paths:
        parser.error("No calibrated .bin captures found")
    mapper, detector = EsamClient(), Detector()
    confirmation, lifecycle, orientation = (
        ObjectConfirmation(),
        ObjectLifecycle(),
        AxialOrientation(),
    )
    rows, objects = [], []
    error = None
    try:
        for path in paths:
            began = time.perf_counter()
            frame = read_frame(path)
            detections = detector(frame)
            candidates, surfaces, timing = mapper.integrate(frame, detections)
            objects = confirmation.update(frame, detections, candidates, surfaces)
            objects = orientation.update(lifecycle.update(frame, objects, surfaces))
            row = dict(
                frame=path.name,
                detections=len(detections),
                candidate_instances=len(candidates),
                objects=len(objects),
                end_to_end_ms=(time.perf_counter() - began) * 1000,
                **timing,
            )
            rows.append(row)
            print(json.dumps(row), flush=True)
        np.savez_compressed(args.output.with_suffix(".npz"), **surfaces)
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"
        raise
    finally:
        mapper.close()
        detector.close()
        args.output.write_text(
            json.dumps(
                dict(
                    model="ESAM-E",
                    revision=REVISION,
                    checkpoint_sha256=CHECKPOINT_SHA256,
                    frames=rows,
                    objects=objects,
                    error=error,
                    accuracy="Not measured: captures do not have instance ground-truth annotations",
                ),
                indent=2,
                allow_nan=False,
            )
        )


if __name__ == "__main__":
    main()
