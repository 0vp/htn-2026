"""Small calibrated captures for protocol and storage tests."""

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from htn_backend.capture.codec import encode
from htn_backend.capture.frame import Frame, FrameHeader
from htn_backend.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


def packet(frame_id=0, epoch=0, timestamp=1, rgb=True):
    image = io.BytesIO()
    if rgb:
        Image.new("RGB", (4, 4), "blue").save(image, format="JPEG")
    header = FrameHeader(
        session_id="capture-a",
        epoch=epoch,
        frame_id=frame_id,
        timestamp_s=timestamp,
        tracking="normal",
        camera_convention="arkit",
        depth_width=4,
        depth_height=4,
        rgb_width=4 if rgb else 0,
        rgb_height=4 if rgb else 0,
        rgb_bytes=len(image.getvalue()),
        fx=2,
        fy=2,
        cx=2,
        cy=2,
        camera_to_world=tuple(np.eye(4).flatten(order="F")),
    )
    return encode(
        Frame(header, np.ones((4, 4), dtype="f4"), np.full((4, 4), 2, dtype="u1"), image.getvalue())
    )


def room(client, device="phone-a"):
    result = client.post("/v1/rooms", json={"name": "Test"})
    assert result.status_code == 201
    code = result.json()["room_id"]
    assert client.post(f"/v1/rooms/{code}/join", json={"device_id": device}).status_code == 200
    return code


def upload(client, code, data, device="phone-a"):
    return client.post(
        f"/v1/rooms/{code}/devices/{device}/frames",
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )
