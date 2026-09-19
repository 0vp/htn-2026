"""Calibrated RGB-D arrays and bounded, pickle-free native worker framing."""

import io
import struct

import cv2
import numpy as np
from PIL import Image

from .config import LABELS

MAX_PACKET = 64_000_000
Y_TO_Z = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)


def pack(**arrays):
    stream = io.BytesIO()
    np.savez(stream, **arrays)
    body = stream.getvalue()
    if len(body) > MAX_PACKET:
        raise ValueError("Hydra packet exceeds memory bound")
    return struct.pack("<I", len(body)) + body


def unpack(body):
    if len(body) > MAX_PACKET:
        raise ValueError("Hydra packet exceeds memory bound")
    with np.load(io.BytesIO(body), allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def prepare(frame, detections, calibration=None):
    h = frame.header
    if not frame.rgb_jpeg:
        raise ValueError("Hydra requires calibrated RGB-D")
    with Image.open(io.BytesIO(frame.rgb_jpeg)) as image:
        color = np.array(image.convert("RGB").resize((h.depth_width, h.depth_height)))
    depth = np.where(
        (frame.confidence >= 1)
        & np.isfinite(frame.depth)
        & (frame.depth >= 0.15)
        & (frame.depth <= 5),
        frame.depth,
        0,
    ).astype("f4")
    labels = np.zeros(depth.shape, dtype=np.int32)
    for d in sorted(detections, key=lambda row: row["score"]):
        if d["mask"].shape != depth.shape or not np.isfinite(d["score"]):
            raise ValueError("invalid Hydra detection")
        if d["score"] >= 0.5 and d["label"] in LABELS:
            labels[d["mask"]] = LABELS.index(d["label"])
    current = (h.depth_width, h.depth_height, h.fx, h.fy, h.cx, h.cy)
    fixed = current if calibration is None else calibration
    if current != fixed:
        width, height, fx, fy, cx, cy = fixed
        rows, cols = np.indices((height, width), dtype=np.float32)
        x, y = (cols - cx) * h.fx / fx + h.cx, (rows - cy) * h.fy / fy + h.cy
        color, depth, labels = (
            cv2.remap(a, x, y, interp, borderMode=cv2.BORDER_CONSTANT)
            for a, interp in (
                (color, cv2.INTER_LINEAR),
                (depth, cv2.INTER_NEAREST),
                (labels, cv2.INTER_NEAREST),
            )
        )
    pose = np.array(h.camera_to_world).reshape(4, 4, order="F").copy()
    if h.camera_convention == "arkit":
        pose = pose @ np.diag([1, -1, -1, 1])
    pose[:3] = Y_TO_Z @ pose[:3]
    return dict(
        color=color,
        depth=depth,
        labels=labels,
        pose=pose,
        calibration=np.array(fixed),
        timestamp=np.array(round(h.timestamp_s * 1e9)),
    ), fixed
