"""Compression, malformed packets, backpressure and WebSocket ingestion."""

import sqlite3
import struct
import zlib
from collections import namedtuple
from dataclasses import replace

import pytest
from conftest import packet, room, upload

from htn_backend.capture.codec import decode
from htn_backend.storage import database


def compressed(data, shuffled=False):
    if shuffled:
        size = struct.unpack_from("<I", data, 4)[0]
        start = 8 + size
        depth = decode(data).depth.astype("<f4").tobytes()
        arranged = b"".join(depth[i::4] for i in range(4))
        data = data[:start] + arranged + data[start + len(depth) :]
    encoder = zlib.compressobj(wbits=-15)
    return (
        (b"R3S1" if shuffled else b"R3Z1")
        + struct.pack("<I", len(data))
        + encoder.compress(data)
        + encoder.flush()
    )


@pytest.mark.parametrize("shuffled", [False, True])
def test_compression_and_same_content_retry(client, shuffled):
    code = room(client)
    data = packet()
    first = upload(client, code, data).json()
    retry = upload(client, code, compressed(data, shuffled)).json()
    assert retry["duplicate"] and retry["sha256"] == first["sha256"]


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"garbage",
        packet()[:-1],
        packet() + b"x",
        compressed(packet()) + b"trailing",
        b"R3Z1" + struct.pack("<I", 14_000_001),
    ],
)
def test_invalid_packet_not_saved(client, data):
    code = room(client)
    assert upload(client, code, data).status_code == 422
    assert client.get(f"/v1/rooms/{code}").json()["frames_stored"] == 0


def test_websocket_retry_http_and_reconnect(client):
    code = room(client)
    path = f"/v1/rooms/{code}/devices/phone-a/stream"
    with client.websocket_connect(path) as ws:
        ws.send_bytes(packet())
        assert ws.receive_json()["stored"]
        ws.send_bytes(b"invalid")
        assert ws.receive_json()["status"] == 422
        ws.send_text("text")
        assert ws.receive_json()["status"] == 422
        ws.send_bytes(packet(1))
        assert ws.receive_json()["frame_id"] == 1
    with client.websocket_connect(path) as ws:
        ws.send_bytes(packet())
        assert ws.receive_json()["duplicate"]
    assert upload(client, code, packet(1)).json()["duplicate"]
    assert client.get(f"/v1/rooms/{code}").json()["frames_stored"] == 2


def test_disk_pressure_does_not_ack(client, monkeypatch):
    code = room(client)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(database.shutil, "disk_usage", lambda _: usage(100, 99, 1))
    assert upload(client, code, packet()).status_code == 507
    assert client.get(f"/v1/rooms/{code}").json()["frames_stored"] == 0


def test_store_failure_does_not_ack(client, monkeypatch):
    code = room(client)

    def fail(*args):
        raise sqlite3.OperationalError("disk error")

    monkeypatch.setattr(client.app.state.store, "save", fail)
    assert upload(client, code, packet()).status_code == 503
    with client.websocket_connect(f"/v1/rooms/{code}/devices/phone-a/stream") as ws:
        ws.send_bytes(packet())
        assert ws.receive_json()["status"] == 503


def test_oversize_and_wrong_content_type(client):
    code = room(client)
    assert upload(client, code, b"x" * 14_000_001).status_code == 413
    assert client.post(f"/v1/rooms/{code}/devices/phone-a/frames", json={}).status_code == 415


def test_confidence_and_pose_validation(client):
    code = room(client)
    data = bytearray(packet(rgb=False))
    start = 8 + struct.unpack_from("<I", data, 4)[0]
    data[start + 16 * 4] = 3
    assert upload(client, code, bytes(data)).status_code == 422
    assert upload(client, code, packet().replace(b'"fx":2.0', b'"fx":0.0')).status_code == 422


def test_transaction_rolls_back_payload_and_counter(client):
    code = room(client)
    store = client.app.state.store
    store.db.execute(
        "CREATE TRIGGER fail_counter BEFORE UPDATE ON totals "
        "BEGIN SELECT RAISE(ABORT, 'storage fault'); END"
    )
    assert upload(client, code, packet()).status_code == 503
    assert client.get(f"/v1/rooms/{code}").json()["frames_stored"] == 0
    assert store.db.execute("SELECT frames FROM totals").fetchone()[0] == 0
    store.db.execute("DROP TRIGGER fail_counter")
    assert upload(client, code, packet()).json()["stored"]


def test_storage_quota_and_connection_membership(client, monkeypatch):
    code = room(client)
    monkeypatch.setattr(database, "MAX_BYTES", 1)
    assert upload(client, code, packet()).status_code == 507
    with client.websocket_connect(f"/v1/rooms/{code}/devices/missing/stream") as ws:
        assert ws.receive_json()["status"] == 409


def test_jpeg_metadata_and_invalid_data(client):
    code = room(client)
    data = packet().replace(b'"rgb_width":4', b'"rgb_width":3')
    assert upload(client, code, data).status_code == 422
    raw = packet()
    # This preserves framing length; the stream itself must still decode as JPEG.
    from htn_backend.capture.codec import decode, encode

    frame = decode(raw)
    frame = replace(frame, rgb_jpeg=b"x" * len(frame.rgb_jpeg))
    assert upload(client, code, encode(frame)).status_code == 422
