"""Image-only inference RPC: no unused depth payload crosses the WAN."""

import io
import struct

import numpy as np
from PIL import Image

from ..capture.frame import Frame, FrameHeader


def encode_image(frame: Frame) -> bytes:
    image = Image.open(io.BytesIO(frame.rgb_jpeg))
    if image.size != (frame.header.rgb_width, frame.header.rgb_height):
        raise ValueError("inference RGB dimensions disagree with header")
    if max(image.size) <= 960 and len(frame.rgb_jpeg) < 1_900_000:
        # The phone already produces calibrated 960px JPEGs. Avoid another lossy encode.
        jpeg = frame.rgb_jpeg
    else:
        image = image.convert("RGB")
        image.thumbnail((960, 960), Image.Resampling.BILINEAR)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        jpeg = buffer.getvalue()
    header = frame.header.model_copy(
        update={"rgb_width": image.width, "rgb_height": image.height, "rgb_bytes": len(jpeg)}
    )
    data = header.model_dump_json().encode()
    return b"R3I1" + struct.pack("<I", len(data)) + data + jpeg


def decode_image(payload: bytes) -> Frame:
    if not 8 <= len(payload) <= 2_000_000 or payload[:4] != b"R3I1":
        raise ValueError("invalid image RPC")
    length = struct.unpack_from("<I", payload, 4)[0]
    if not 0 < length <= 16_384 or 8 + length > len(payload):
        raise ValueError("invalid image header")
    header = FrameHeader.model_validate_json(payload[8 : 8 + length])
    # Depth buffers supply dimensions only. This object must never enter a mapper.
    shape = (header.depth_height, header.depth_width)
    return Frame(
        header,
        np.zeros(shape, dtype=np.float32),
        np.zeros(shape, dtype=np.uint8),
        payload[8 + length :],
    )
