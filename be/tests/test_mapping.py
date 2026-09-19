"""Publication consistency, coordinate isolation, recovery and registration checks."""

import json
import struct
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import packet, room, upload

from htn_backend.processing.alignment import Alignment, stream_key
from htn_backend.processing.mesh import glb
from htn_backend.processing.room import RoomProcessor
from htn_backend.processing.state import ProcessingState
from htn_backend.registration.features import Keyframe
from htn_backend.registration.hybrid import register
from htn_backend.storage.database import Store


class Native:
    def __init__(self):
        self.frames = []

    def integrate(self, frame, detections):
        self.frames.append(frame)
        return {"updated": False}

    def flush(self):
        return {
            "vertices": np.array([[0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype="f4"),
            "triangles": np.array([[0, 1, 2]], dtype="i4"),
            "nodes": np.array("[]"),
            "updated": True,
            "agents": np.empty((0, 8)),
        }

    def close(self):
        pass


class Detector:
    def __init__(self):
        self.features = SimpleNamespace(extract=lambda f: SimpleNamespace(pose=np.eye(4)))

    def __call__(self, frame):
        return []


def test_atomic_map_search_and_etag(client):
    code = room(client)
    receipt = upload(client, code, packet()).json()
    state = ProcessingState(client.app.state.store)
    mesh = glb(np.eye(3), np.array([[0, 1, 2]]))
    assert struct.unpack_from("<III", mesh) == (0x46546C67, 2, len(mesh))
    state.publish(
        code,
        mesh,
        [{"object_id": "1", "label": "bottle", "center_m": [1, 2, 3]}],
        {"backend": "hydra"},
        [receipt["sequence"]],
    )
    assert client.get(f"/v1/rooms/{code}/processing").json()["mapped"] == 1
    result = client.get(f"/v1/rooms/{code}/objects", params={"q": "bottle"}).json()
    assert result["objects"][0]["center_m"] == [1, 2, 3]
    response = client.get(f"/v1/rooms/{code}/mesh.glb")
    assert response.content == mesh
    assert (
        client.get(
            f"/v1/rooms/{code}/mesh.glb", headers={"If-None-Match": response.headers["etag"]}
        ).status_code
        == 304
    )
    other = room(client)
    assert client.get(f"/v1/rooms/{other}/objects").status_code == 409
    assert state.search(code, '" OR room_id:*') == []
    state.publish(code, mesh, [], {}, [])
    assert state.search(code, "bottle") == []


def test_replay_order_and_unaligned_origin(client):
    code = room(client)
    for index, stamp in enumerate([99999, 1, 60000]):
        assert upload(client, code, packet(index, timestamp=stamp)).status_code == 200
    assert upload(client, code, packet(0, epoch=1)).status_code == 200
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Native)
    try:
        assert processor.step()
        assert not processor.step()
        status = state.status(code)
        assert (status["mapped"], status["awaiting_alignment"], status["pending"]) == (3, 1, 0)
        times = [f.header.timestamp_s for f in processor.mapper.frames]
        assert times == sorted(times) and len(set(times)) == 3
        assert [f.provenance["capture_timestamp_s"] for f in processor.mapper.frames] == [
            99999,
            1,
            60000,
        ]
        processor.reset()
        assert processor.step()
        assert state.status(code)["mapped"] == 3
        assert state.snapshot(code)["metadata"]["integrated_frames"] == 3
    finally:
        processor.close()


def test_native_failure_does_not_ack_mapping(client):
    class Broken(Native):
        def flush(self):
            raise RuntimeError("worker died")

    code = room(client)
    upload(client, code, packet())
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Broken)
    try:
        with pytest.raises(RuntimeError):
            processor.step()
        assert state.status(code)["pending"] == 1
        assert state.status(code)["mapped"] == 0
        assert len(state.store.frames(code, 0, 10)) == 1
    finally:
        processor.close()


def test_refused_alignment_can_be_retried_after_restart(tmp_path):
    store = Store(tmp_path)
    state = ProcessingState(store)
    code = store.create("Room")["room_id"]
    state.align(
        code, "origin", {"status": "anchor", "room_from_local": np.eye(4).flatten().tolist()}
    )
    row = {"device_id": "two", "header": {"session_id": "scan", "epoch": 0}}
    state.align(code, stream_key(row), {"status": "insufficient_matches"})
    alignment = Alignment(state, code, None)
    assert alignment.transform(row) is None
    assert stream_key(row) not in alignment.transforms
    store.close()


def test_held_out_registration_accepts_rigid_and_rejects_wrong_place():
    rng = np.random.default_rng(71)
    points = rng.uniform(-1, 1, (500, 3))
    moved = points + [0.4, 0, -0.2]
    left = [Keyframe(i, np.eye(4), points, np.empty((0, 32)), points) for i in range(5)]
    right = [Keyframe(i, np.eye(4), moved, np.empty((0, 32)), moved) for i in range(5)]

    def match(a, b):
        return a.points, b.points

    result = register(left, right, match)
    assert result["status"] == "aligned"
    assert np.allclose(
        np.array(result["room_from_local"]).reshape(4, 4, order="F")[:3, 3],
        [0.4, 0, -0.2],
        atol=1e-6,
    )
    wrong = [
        Keyframe(
            i,
            np.eye(4),
            rng.uniform(-1, 1, (500, 3)),
            np.empty((0, 32)),
            rng.uniform(-2, 2, (500, 3)),
        )
        for i in range(5)
    ]
    assert register(left, wrong, match)["status"] != "aligned"


def test_fts_and_mesh_survive_database_restart(tmp_path):
    store = Store(tmp_path)
    state = ProcessingState(store)
    code = store.create("Room")["room_id"]
    mesh = glb(np.empty((0, 3)), np.empty((0, 3)))
    state.publish(code, mesh, [{"object_id": "tv1", "label": "tv"}], {}, [])
    store.close()
    store = Store(tmp_path)
    state = ProcessingState(store)
    assert state.snapshot(code)["mesh"] == mesh
    assert state.search(code, "tv")[0]["object_id"] == "tv1"
    document_size = struct.unpack_from("<I", mesh, 12)[0]
    assert json.loads(mesh[20 : 20 + document_size])["scenes"] == [{"nodes": []}]
    store.close()


def test_replay_keeps_last_complete_publication(client):
    code = room(client)
    for i in range(9):
        upload(client, code, packet(i))
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Native)
    try:
        while processor.step():
            pass
        old = state.snapshot(code)
        processor.reset()
        assert processor.step()
        assert state.snapshot(code)["revision"] == old["revision"]
        assert state.snapshot(code)["metadata"]["integrated_frames"] == 9
        while processor.step():
            pass
        assert state.status(code)["mapped"] == 9
        assert state.snapshot(code)["metadata"]["integrated_frames"] == 9
    finally:
        processor.close()


def test_object_evidence_is_room_scoped_and_replaced(client):
    code, other = room(client), room(client)
    state = ProcessingState(client.app.state.store)
    state.publish(
        code,
        b"mesh",
        [{"object_id": "tv", "label": "tv"}],
        {},
        [],
        {"tv": {"digest": "abc", "jpeg": b"jpeg", "source": {"frame_id": 1}}},
    )
    assert client.get(f"/v1/rooms/{code}/objects/tv/evidence.jpg").content == b"jpeg"
    assert client.get(f"/v1/rooms/{other}/objects/tv/evidence.jpg").status_code == 404
    state.publish(code, b"mesh", [], {}, [])
    assert client.get(f"/v1/rooms/{code}/objects/tv/evidence.jpg").status_code == 404
