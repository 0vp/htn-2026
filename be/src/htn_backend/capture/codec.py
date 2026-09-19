"""R3D1: little-endian header length, JSON, float32 depth, confidence, JPEG."""

import struct
import zlib
from pathlib import Path

import numpy as np

from .frame import Frame, FrameHeader

MAGIC = b"R3D1"
MAX_HEADER_BYTES = 16_384
MAX_FRAME_BYTES = 14_000_000


def encode(frame: Frame) -> bytes:
    header = frame.header.model_dump_json().encode("utf-8")
    if len(header) > MAX_HEADER_BYTES:
        raise ValueError("header is too large")
    return b"".join(
        [
            MAGIC,
            struct.pack("<I", len(header)),
            header,
            frame.depth.astype("<f4").tobytes(),
            frame.confidence.tobytes(),
            frame.rgb_jpeg,
        ]
    )


def decode(payload: bytes) -> Frame:
    shuffled = payload[:4] == b"R3S1"
    if payload[:4] in (b"R3Z1", b"R3S1"):
        if not 8 <= len(payload) <= MAX_FRAME_BYTES:
            raise ValueError("compressed frame exceeds size limit")
        expected = struct.unpack_from("<I", payload, 4)[0]
        if not 8 <= expected <= MAX_FRAME_BYTES:
            raise ValueError("invalid expanded frame size")
        inflater = zlib.decompressobj(wbits=-15)
        try:
            expanded = inflater.decompress(payload[8:], expected + 1)
        except zlib.error as error:
            raise ValueError("invalid compressed frame") from error
        if len(expanded) != expected or not inflater.eof or inflater.unused_data:
            raise ValueError("compressed frame size mismatch or trailing data")
        payload = expanded
    if not 8 <= len(payload) <= MAX_FRAME_BYTES or payload[:4] != MAGIC:
        raise ValueError("invalid R3D1 frame or frame exceeds size limit")
    header_size = struct.unpack_from("<I", payload, 4)[0]
    if not 0 < header_size <= MAX_HEADER_BYTES or 8 + header_size > len(payload):
        raise ValueError("invalid header length")
    header = FrameHeader.model_validate_json(payload[8 : 8 + header_size])
    pixels = header.depth_width * header.depth_height
    offset = 8 + header_size
    if len(payload) != offset + pixels * 5 + header.rgb_bytes:
        raise ValueError("truncated payload or unexpected trailing bytes")
    if shuffled:
        shuffled_depth = np.frombuffer(payload, dtype=np.uint8, count=pixels * 4, offset=offset)
        restored = shuffled_depth.reshape(4, pixels).T.copy().tobytes()
        payload = payload[:offset] + restored + payload[offset + pixels * 4 :]
    shape = (header.depth_height, header.depth_width)
    depth = np.frombuffer(payload, dtype="<f4", count=pixels, offset=offset).reshape(shape)
    confidence = np.frombuffer(
        payload,
        dtype=np.uint8,
        count=pixels,
        offset=offset + pixels * 4,
    ).reshape(shape)
    return Frame(header, depth, confidence, payload[offset + pixels * 5 :])


def read_frame(path: Path) -> Frame:
    with path.open("rb") as stream:
        payload = stream.read(MAX_FRAME_BYTES + 1)
    return decode(payload)
