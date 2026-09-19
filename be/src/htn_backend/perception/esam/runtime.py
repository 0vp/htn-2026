"""Headless upstream ESAM-E runner, executed in its isolated CUDA environment."""

import argparse
import contextlib
import hashlib
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

from ...mapping.hydra.packet import MAX_PACKET, Y_TO_Z, pack, unpack
from .preprocess import Preprocessor

REVISION = "188fc6de44f7577fecec2d69b75c7adbd9992251"
CHECKPOINT_SHA256 = "161f575838d2ef11d35fc17fecb8e3b292f4d0813945de457e7bc89f643a2329"
FASTSAM_SHA256 = "c0be4e7ddbe4c15333d15a859c676d053c486d0a746a3be6a7a9790d52a9b6d7"
WINDOW_FRAMES = 32


class Runtime:
    def __init__(self, upstream, checkpoint, fastsam):
        import torch
        from mmengine.config import Config
        from mmengine.registry import init_default_scope
        from mmengine.runner import load_checkpoint

        np.random.seed(0)
        torch.manual_seed(0)
        digest = self.digest(checkpoint)
        if digest != CHECKPOINT_SHA256:
            raise ValueError("ESAM-E checkpoint checksum mismatch")
        if self.digest(fastsam) != FASTSAM_SHA256:
            raise ValueError("FastSAM checkpoint checksum mismatch")
        sys.path.insert(0, str(Path(upstream).resolve()))
        from mmdet3d.registry import MODELS

        config = Config.fromfile(str(Path(upstream) / "configs/ESAM-E_CA/ESAM-E_online_stream.py"))
        init_default_scope("mmdet3d")
        self.model = MODELS.build(config.model)
        load_checkpoint(self.model, checkpoint, map_location="cpu", strict=True)
        self.model.map_to_rec_pcd = False
        self.model.cuda().eval()
        self.preprocessor = Preprocessor(config, fastsam)
        self.torch = torch
        self.reset()

    @staticmethod
    def digest(path):
        h = hashlib.sha256()
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    def reset(self):
        if hasattr(self.model, "online_merger"):
            del self.model.online_merger
        if getattr(self.model, "memory", None) is not None:
            self.model.memory.reset()
        self.points = []

    def predict(self, arrays):
        from mmdet3d.structures import Det3DDataSample, PointData
        from mmengine.dataset import pseudo_collate

        if bool(arrays.get("reset", False)) or len(self.points) >= WINDOW_FRAMES:
            self.reset()
        start = time.perf_counter()
        groups, points = self.preprocessor.process_single_frame(
            arrays["color"], arrays["depth_mm"], arrays["pose"], arrays["intrinsic"]
        )
        preprocessed = time.perf_counter()
        sample = Det3DDataSample()
        sample.gt_pts_seg = PointData(sp_pts_mask=self.torch.from_numpy(groups).long().cuda())
        batch = pseudo_collate(
            [
                dict(
                    inputs=dict(points=self.torch.from_numpy(points).float().cuda()),
                    data_samples=sample,
                )
            ]
        )
        with self.torch.inference_mode():
            result = self.model.test_step(batch)[0].pred_pts_seg
        inferred = time.perf_counter()
        self.points.append(points[:, :3].astype(np.float32))
        cloud = np.concatenate(self.points) @ Y_TO_Z.astype(np.float32)
        masks, scores = result.pts_instance_mask[0], result.instance_scores
        if masks.shape != (len(scores), len(cloud)):
            raise ValueError("ESAM merger masks do not match accumulated point history")
        instances, kept_scores = [], []
        for mask, score in zip(masks, scores, strict=True):
            if score < 0.3 or np.count_nonzero(mask) < 20:
                continue
            xyz = cloud[np.asarray(mask, dtype=bool)]
            _, indices = np.unique(np.floor(xyz / 0.02).astype(np.int64), axis=0, return_index=True)
            xyz = xyz[indices]
            if len(xyz) > 4000:
                xyz = xyz[np.linspace(0, len(xyz) - 1, 4000).astype(int)]
            instances.append(xyz)
            kept_scores.append(score)
        return dict(
            points=np.concatenate(instances) if instances else np.empty((0, 3), dtype=np.float32),
            offsets=np.cumsum([0] + [len(x) for x in instances], dtype=np.int64),
            scores=np.asarray(kept_scores, dtype=np.float32),
            elapsed_ms=np.array((time.perf_counter() - start) * 1000),
            preprocess_ms=np.array((preprocessed - start) * 1000),
            network_ms=np.array((inferred - preprocessed) * 1000),
            window_frames=np.array(len(self.points)),
        )


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        block = stream.read(size - len(chunks))
        if not block:
            raise EOFError("Truncated ESAM request")
        chunks.extend(block)
    return bytes(chunks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--fastsam", required=True)
    args = parser.parse_args()
    # Native libraries can print directly to fd 1; protect binary framing from them.
    output = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    with contextlib.redirect_stdout(sys.stderr):
        runtime = Runtime(args.upstream, args.checkpoint, args.fastsam)
        while True:
            header = sys.stdin.buffer.read(4)
            if not header:
                return
            if len(header) != 4:
                raise EOFError("Truncated ESAM packet header")
            size = struct.unpack("<I", header)[0]
            if size > MAX_PACKET:
                raise ValueError("ESAM request exceeds memory bound")
            request = unpack(read_exact(sys.stdin.buffer, size))
            result = runtime.predict(request)
            output.write(pack(**result))
            output.flush()


if __name__ == "__main__":
    main()
