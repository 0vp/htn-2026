"""Compare sampled-pixel preprocessing to the pinned ESAM reference on real RGB-D."""

import argparse
import json
import runpy
import sys
import time
from pathlib import Path

import numpy as np

from htn_backend.perception.esam.preprocess import Preprocessor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", type=Path, help="Calibrated ESAM input .npz files")
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--fastsam", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.upstream.resolve()))
    from vis_demo.utils.stream_data_utils import DataPreprocessor

    config = runpy.run_path(str(args.upstream / "configs/ESAM-E_CA/ESAM-E_online_stream.py"))
    reference = DataPreprocessor(config, args.fastsam)
    candidate = Preprocessor.__new__(Preprocessor)
    candidate.masks = reference.mask_generator
    candidate.mean, candidate.std = np.array(config["color_mean"]), np.array(config["color_std"])
    paths = sorted(args.captures.glob("*.npz"))
    if not paths:
        parser.error("No prepared captures found")

    def run(processor, arrays):
        np.random.seed(0)
        began = time.perf_counter()
        groups, points = processor.process_single_frame(
            arrays["color"], arrays["depth_mm"], arrays["pose"], arrays["intrinsic"]
        )
        return groups, points, (time.perf_counter() - began) * 1000

    with np.load(paths[0], allow_pickle=False) as first:
        run(reference, first)
        run(candidate, first)
    rows = []
    for path in paths:
        with np.load(path, allow_pickle=False) as arrays:
            for trial in range(3):
                processors = (reference, candidate) if trial % 2 == 0 else (candidate, reference)
                result = [run(processor, arrays) for processor in processors]
                base, fast = result if trial % 2 == 0 else result[::-1]
                row = dict(
                    frame=path.name,
                    trial=trial,
                    reference_ms=base[2],
                    candidate_ms=fast[2],
                    groups_identical=bool(np.array_equal(base[0], fast[0])),
                    maximum_point_error=float(np.max(abs(base[1] - fast[1]))),
                )
                rows.append(row)
                print(json.dumps(row), flush=True)
    equivalent = all(r["groups_identical"] and r["maximum_point_error"] < 1e-6 for r in rows)
    report = dict(
        equivalent=equivalent,
        frames=len(paths),
        trials=len(rows),
        rows=rows,
        reference_median_ms=float(np.median([r["reference_ms"] for r in rows])),
        candidate_median_ms=float(np.median([r["candidate_ms"] for r in rows])),
        accuracy="Preprocessing equivalence only; not a segmentation accuracy benchmark",
    )
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False))
    if not equivalent:
        raise SystemExit("Candidate differs from reference; do not promote")


if __name__ == "__main__":
    main()
