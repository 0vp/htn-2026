"""Room leadership is persistent membership metadata, independent of scan origins."""

import sqlite3

import pytest

from htn_backend.storage.database import Store


def test_create_registers_leader_and_join_never_transfers_it(client):
    response = client.post("/v1/rooms", json={"name": "Robot room", "device_id": "leader"})
    assert response.status_code == 201
    room = response.json()
    assert room["leader_device_id"] == "leader"
    assert [d["device_id"] for d in room["devices"]] == ["leader"]
    for device in ["helper", "leader", "helper"]:
        joined = client.post(f"/v1/rooms/{room['room_id']}/join", json={"device_id": device})
        assert joined.status_code == 200
        assert joined.json()["leader_device_id"] == "leader"
    assert len(joined.json()["devices"]) == 2
    assert client.get("/v1/rooms").json()["rooms"][0]["leader_device_id"] == "leader"


def test_existing_clients_remain_valid_and_do_not_claim_leadership(client):
    room = client.post("/v1/rooms", json={"name": "Legacy room"}).json()
    assert room["leader_device_id"] is None
    joined = client.post(f"/v1/rooms/{room['room_id']}/join", json={"device_id": "helper"}).json()
    assert joined["leader_device_id"] is None
    assert client.post("/v1/rooms", json={"device_id": "../bad"}).status_code == 422


def test_membership_failure_rolls_back_room(client):
    store = client.app.state.store
    store.db.execute("""CREATE TRIGGER fail_creator BEFORE INSERT ON devices
        BEGIN SELECT RAISE(ABORT,'test failure'); END""")
    store.db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        store.create("Atomic", "leader")
    assert store.rooms() == []


def test_legacy_migration_and_restart_preserve_leadership(tmp_path):
    db = sqlite3.connect(tmp_path / "rooms.sqlite3")
    db.execute(
        "CREATE TABLE rooms(room_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "created_at REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute("INSERT INTO rooms VALUES('ABCDEF12','Old room',0,0)")
    db.commit()
    db.close()
    store = Store(tmp_path)
    assert store.room("ABCDEF12")["leader_device_id"] is None
    new = store.create("New room", "leader")
    store.close()
    store = Store(tmp_path)
    assert store.room(new["room_id"])["leader_device_id"] == "leader"
    assert store.room(new["room_id"])["devices"][0]["device_id"] == "leader"
    store.close()
