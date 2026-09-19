"""Retention pressure preserves live work and sparse references to old places."""

import time
from dataclasses import replace

import numpy as np
from conftest import packet, room
from test_mapping import Detector, Native

from htn_backend.capture.codec import decode
from htn_backend.processing.atlas.references import References
from htn_backend.processing.room import RoomProcessor
from htn_backend.processing.state import ProcessingState
from htn_backend.storage import retention
from htn_backend.storage.database import Store


def test_sparse_reference_bank_keeps_old_regions_but_replaces_redundant_views(tmp_path):
    store = Store(tmp_path)
    refs = References(store, store.create("Map")["room_id"])
    frame = decode(packet())
    for i in range(40):
        pose = np.eye(4)
        pose[0, 3] = i * 3
        observed = replace(
            frame,
            header=frame.header.model_copy(
                update={"camera_to_world": tuple(pose.flatten(order="F"))}
            ),
        )
        refs.save(i, observed)
    recent = refs.frames()
    older = refs.frames(before=min(n for n, _ in recent))
    assert len(recent) == 24 and len(older) == 16
    for i in range(40, 50):
        refs.save(i, frame)
    assert (
        store.db.execute(
            'SELECT COUNT(*) FROM alignment_references WHERE bucket="0,0,0,0"'
        ).fetchone()[0]
        == 2
    )
    assert store.db.execute("SELECT COUNT(*) FROM alignment_references").fetchone()[0] == 41
    store.close()


def test_storage_pressure_never_reclaims_active_or_unaligned_frames(client, monkeypatch):
    store = client.app.state.store
    code = room(client)
    state = ProcessingState(store)
    processor = RoomProcessor(state, code, Detector(), mapper_factory=Native)
    try:
        first = decode(packet())
        store.save(code, "phone-a", first, packet())
        processor.step()
        processor.seal()
        store.save(code, "phone-a", decode(packet(1, epoch=1)), packet(1, epoch=1))
        store.save(code, "phone-a", decode(packet(2)), packet(2))
        processor.step()
        monkeypatch.setattr(retention, "RAW_TARGET_BYTES", 1)
        result = retention.cleanup(store)
        assert result["frames_cleaned"] == 1
        assert len(store.payload(code, 2)) and len(store.payload(code, 3))
        assert state.status(code)["mapped"] == 2
        assert state.status(code)["awaiting_alignment"] == 1
        processor.last_work = time.monotonic() - 31
        assert not processor.step()
        assert processor.atlas.frames == 2
    finally:
        processor.close()
