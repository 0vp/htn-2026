"""Bounded image evidence tied to a measured object's mask and capture identity."""

import hashlib
from io import BytesIO

import numpy as np
from PIL import Image

from ...perception.orientation import upright_quarter_turns


def crop(frame, detection) -> dict | None:
    mask = detection["mask"]
    y, x = np.where(mask)
    if len(x) < 6 or not frame.rgb_jpeg:
        return None
    h = frame.header
    with Image.open(BytesIO(frame.rgb_jpeg)) as image:
        if image.size != (h.rgb_width, h.rgb_height):
            raise ValueError("evidence image dimensions disagree with calibration")
        sx, sy = image.width / mask.shape[1], image.height / mask.shape[0]
        pad = max(2, round(0.05 * max(x.max() - x.min(), y.max() - y.min())))
        box = [
            max(0, (x.min() - pad) * sx),
            max(0, (y.min() - pad) * sy),
            min(image.width, (x.max() + 1 + pad) * sx),
            min(image.height, (y.max() + 1 + pad) * sy),
        ]
        photo = image.crop(box).convert("RGB")
    photo = photo.rotate(90 * upright_quarter_turns(h), expand=True)
    photo.thumbnail((224, 224))
    output = BytesIO()
    photo.save(output, format="JPEG", quality=85)
    data = output.getvalue()
    if len(data) > 65_536:
        return None
    return dict(
        jpeg=data,
        digest=hashlib.sha256(data).hexdigest(),
        source=dict(frame.provenance or {})
        | dict(
            capture_session_id=h.session_id,
            capture_epoch=h.epoch,
            capture_frame_id=h.frame_id,
            capture_timestamp_s=h.timestamp_s,
        ),
        bbox_rgb=box,
        quality=float(len(x) * detection["score"]),
    )
