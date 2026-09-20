"""HTN_ROOM_ID pins the service to one always-open room."""

from htn_backend.storage.database import Store


def test_single_room_purges_others_and_never_closes(tmp_path, monkeypatch):
    store = Store(tmp_path)
    other = store.create("Old", "device-a")["room_id"]
    store.close()

    monkeypatch.setenv("HTN_ROOM_ID", "a0000001")
    store = Store(tmp_path)
    assert [r["room_id"] for r in store.rooms()] == ["A0000001"]
    assert other != "A0000001"
    assert store.db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0

    created = store.create("Anything", "device-b")
    assert created["room_id"] == "A0000001"
    assert [d["device_id"] for d in created["devices"]] == ["device-b"]
    assert created["leader_device_id"] == "device-b"
    assert store.join("A0000001", "device-c", "iPhone")["leader_device_id"] == "device-b"
    assert store.create("x", "device-c")["leader_device_id"] == "device-c"
    assert store.close_room("A0000001")["closed"] in (0, False)
    store.member("A0000001", "device-b")
    store.close()
