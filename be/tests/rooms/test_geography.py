import json
from dataclasses import replace

import numpy as np
import pytest
from conftest import packet, room, upload
from fastapi.testclient import TestClient
from pydantic import ValidationError

from htn_backend.capture.codec import decode, encode
from htn_backend.capture.frame import FrameHeader
from htn_backend.main import create_app


def anchor(accuracy=20, timestamp=100, heading=True):
    pose = dict(
        timestamp_unix_s=timestamp,
        pose_timestamp_s=1,
        pose_time_offset_s=0.1,
        camera_to_world=np.eye(4).flatten(order="F").tolist(),
    )
    return dict(
        **pose,
        latitude=43.5,
        longitude=-79.5,
        horizontal_accuracy_m=accuracy,
        heading=dict(
            **pose,
            degrees=90,
            accuracy_degrees=12,
            reference="true_north",
            reference_direction_world=[1, 0, 0],
        )
        if heading
        else None,
    )


def geo_packet(index=0, epoch=0, **kwargs):
    frame = decode(packet(index, epoch))
    header = FrameHeader.model_validate(
        {**frame.header.model_dump(), "geographic_anchor": anchor(**kwargs)}
    )
    return encode(replace(frame, header=header))


def test_geography_http_websocket_restart_and_retention(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        code, other = room(client), room(client)
        payload = geo_packet()
        with client.websocket_connect(f"/v1/rooms/{code}/devices/phone-a/stream") as ws:
            ws.send_bytes(payload)
            assert ws.receive_json()["stored"]
        assert upload(client, code, payload).json()["duplicate"]
        saved = client.get(f"/v1/rooms/{code}/geography").json()
        assert saved["approximate"] and len(saved["anchors"]) == 1
        assert saved["anchors"][0]["anchor"]["latitude"] == 43.5
        assert client.get(f"/v1/rooms/{other}/geography").json()["anchors"] == []
        assert client.get(f"/v1/rooms/{code}/processing").json()["geography"] == saved
        assert np.array_equal(decode(payload).depth, decode(packet()).depth)
        assert decode(payload).header.camera_to_world == decode(packet()).header.camera_to_world
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/v1/rooms/{code}/geography").json() == saved
        assert upload(client, code, geo_packet(1, accuracy=40, timestamp=110)).status_code == 200
        assert client.get(f"/v1/rooms/{code}/geography").json() == saved
        upload(client, code, geo_packet(2, accuracy=10, timestamp=120))
        upload(client, code, geo_packet(3, accuracy=2, timestamp=105))  # Out of order.
        result = client.get(f"/v1/rooms/{code}/geography").json()
        assert result["anchors"][0]["anchor"]["horizontal_accuracy_m"] == 10
        upload(client, code, geo_packet(0, epoch=1, accuracy=30, timestamp=140))
        assert len(client.get(f"/v1/rooms/{code}/geography").json()["anchors"]) == 2
    # Raw retention cannot erase the independent geographic record.
    import sqlite3

    with sqlite3.connect(tmp_path / "rooms.sqlite3") as db:
        db.execute("UPDATE frames SET payload=x''")
    with TestClient(create_app(tmp_path)) as client:
        assert len(client.get(f"/v1/rooms/{code}/geography").json()["anchors"]) == 2


def test_legacy_canonical_header_stays_identical():
    frame = decode(packet())
    assert frame.header.geographic_anchor is None
    payload = encode(frame)
    size = int.from_bytes(payload[4:8], "little")
    assert "geographic_anchor" not in json.loads(payload[8 : 8 + size])


@pytest.mark.parametrize(
    "changes",
    [
        {"latitude": 91},
        {"longitude": float("nan")},
        {"horizontal_accuracy_m": -1},
        {"pose_time_offset_s": 1},
        {"camera_to_world": [0] * 16},
    ],
)
def test_bad_geographic_readings(changes):
    frame = decode(packet())
    with pytest.raises(ValidationError):
        FrameHeader.model_validate(
            {**frame.header.model_dump(), "geographic_anchor": {**anchor(), **changes}}
        )


def test_heading_upgrade_does_not_discard_better_position(client):
    code = room(client)
    upload(client, code, geo_packet(0, accuracy=5, heading=False))
    upload(client, code, geo_packet(1, accuracy=30, timestamp=110, heading=True))
    assert (
        client.get(f"/v1/rooms/{code}/geography").json()["anchors"][0]["anchor"].get("heading")
        is None
    )
    upload(client, code, geo_packet(2, accuracy=5, timestamp=120, heading=True))
    assert (
        client.get(f"/v1/rooms/{code}/geography").json()["anchors"][0]["anchor"]["heading"][
            "reference"
        ]
        == "true_north"
    )
