"""Cumulative mapping survives rollover, cleanup, crashes and late alignment."""

import sqlite3
from dataclasses import replace

import numpy as np
import pytest
from conftest import packet, room, upload
from test_mapping import Detector, Native

from htn_backend.capture.codec import decode, encode
from htn_backend.processing.alignment import stream_key
from htn_backend.processing.room import RoomProcessor
from htn_backend.processing.state import ProcessingState
from htn_backend.storage.database import StoreError
from htn_backend.storage.retention import cleanup


def drain(processor):
    for _ in range(3000):
        if not processor.step():
            return
    raise AssertionError("Processor did not drain")


def append(state, code, index, epoch=0, x=0):
    frame = decode(packet(index, epoch))
    pose = np.eye(4)
    pose[0, 3] = x
    frame = replace(
        frame,
        header=frame.header.model_copy(update={"camera_to_world": tuple(pose.flatten(order="F"))}),
    )
    return state.store.save(code, "phone-a", frame, encode(frame))


def test_more_than_previous_limit_cumulative_and_bounded(client):
    code = room(client)
    state = ProcessingState(client.app.state.store)
    workers = []

    def factory():
        native = Native()
        workers.append(native)
        return native

    processor = RoomProcessor(state, code, Detector(), mapper_factory=factory)
    try:
        for index in range(1808):
            append(state, code, index)
        drain(processor)
        assert state.status(code)["mapped"] == 1808
        assert state.snapshot(code)["metadata"]["integrated_frames"] == 1808
        assert max(len(worker.frames) for worker in workers) <= 256
        assert processor.atlas.generation == 7
        # Repeated scans replace cells instead of appending duplicate full meshes.
        assert state.snapshot(code)["metadata"]["triangles"] == 1
        processor.seal()
        assert state.snapshot(code)["metadata"]["active_segment_frames"] == 0
        state.store.db.execute("UPDATE frames SET received_at=0")
        state.store.db.commit()
        while cleanup(state.store)["frames_cleaned"]:
            pass
        assert state.status(code)["raw_frames_retained"] == 0
        assert state.status(code)["mapped"] == 1808
        processor.close()
        processor = RoomProcessor(state, code, Detector(), mapper_factory=factory)
        append(state, code, 1808)
        drain(processor)
        assert state.snapshot(code)["metadata"]["integrated_frames"] == 1809
        assert state.status(code)["pending"] == 0
    finally:
        processor.close()


def test_checkpoint_failure_never_makes_raw_eligible_for_cleanup(client):
    code = room(client)
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Native)
    try:
        append(state, code, 0)
        drain(processor)
        state.store.db.execute("""CREATE TRIGGER fail_seal BEFORE UPDATE ON atlas_state
            BEGIN SELECT RAISE(ABORT,'crash'); END""")
        state.store.db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            processor.seal()
        assert state.store.db.execute("SELECT archived FROM frames").fetchone()[0] == 0
        assert state.store.db.execute("SELECT COUNT(*) FROM atlas_tiles").fetchone()[0] == 0
        assert cleanup(state.store, now=10**12)["frames_cleaned"] == 0
        assert len(state.store.payload(code, 1)) > 0
    finally:
        processor.close()


def test_cleaned_payload_is_gone_but_retry_is_still_idempotent(client):
    code = room(client)
    data = packet()
    receipt = upload(client, code, data).json()
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Native)
    try:
        drain(processor)
        processor.seal()
        assert cleanup(state.store, now=10**12)["frames_cleaned"] == 1
        assert client.get(f"/v1/rooms/{code}/frames/{receipt['sequence']}").status_code == 410
        duplicate = upload(client, code, data).json()
        assert duplicate["duplicate"] and duplicate["sequence"] == receipt["sequence"]
        assert state.store.room(code)["frames_stored"] == 1
        assert state.store.room(code)["bytes_stored"] == 0
        assert state.store.db.execute("SELECT bytes FROM totals").fetchone()[0] == 0
        assert state.store.frames(code, 0, 1)[0]["raw_available"] == 0
        assert len(processor.alignment.references.frames()) == 1
    finally:
        processor.close()


def test_late_origin_after_checkpoint_cleanup_keeps_previous_map(client):
    code = room(client)
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Native)
    try:
        append(state, code, 0)
        append(state, code, 1, epoch=1)
        drain(processor)
        processor.seal()
        cleanup(state.store, now=10**12)
        assert state.status(code)["awaiting_alignment"] == 1
        rows = state.store.active_frames(code, 0, 10)
        assert len(rows) == 1
        processor.alignment.save(
            stream_key(rows[0]),
            {"status": "aligned", "room_from_local": np.eye(4).flatten().tolist()},
        )
        processor.reset()
        drain(processor)
        assert state.status(code)["mapped"] == 2
        assert state.status(code)["awaiting_alignment"] == 0
        assert state.snapshot(code)["metadata"]["integrated_frames"] == 2
        with pytest.raises(StoreError) as error:
            state.store.payload(code, 1)
        assert error.value.status == 410
    finally:
        processor.close()


def test_large_room_recenters_native_worker_and_preserves_earlier_surfaces(client):
    code = room(client)
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Native)
    try:
        append(state, code, 0, x=20)
        append(state, code, 1, x=40)
        drain(processor)
        assert state.snapshot(code)["metadata"]["integrated_frames"] == 2
        assert state.snapshot(code)["metadata"]["triangles"] == 2
        assert processor.atlas.generation == 1
        assert abs(processor.mapper.frames[0].header.camera_to_world[12]) < 1e-6
        group = next(iter(processor.atlas.groups.values()))
        assert group[..., 0].min() >= 20
    finally:
        processor.close()
