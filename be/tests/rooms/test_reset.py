"""Resetting a room forgets its captures and map but keeps the room and its members."""

from conftest import packet, room, upload
from test_mapping import Detector, Native

from htn_backend.processing.room import RoomProcessor
from htn_backend.processing.state import ProcessingState


def test_reset_forgets_captures_and_map(client):
    code = room(client)
    for index in range(3):
        assert upload(client, code, packet(index)).status_code == 200
    state = ProcessingState(client.app.state.store)
    processor = RoomProcessor(state, code, Detector(), Native)
    while processor.step():
        pass
    processor.close(checkpoint=True)
    assert client.get(f"/v1/rooms/{code}/processing").json()["map"]

    result = client.post(f"/v1/rooms/{code}/reset")
    assert result.status_code == 200
    body = result.json()
    assert body["frames_stored"] == 0 and body["reset_count"] == 1
    assert [d["device_id"] for d in body["devices"]] == ["phone-a"]
    status = client.get(f"/v1/rooms/{code}/processing").json()
    assert status["map"] is None and status["mapped"] == 0 and status["pending"] == 0
    assert client.get(f"/v1/rooms/{code}/frames").json()["frames"] == []
    totals = client.app.state.store.db.execute("SELECT bytes,frames FROM totals").fetchone()
    assert tuple(totals) == (0, 0)

    # The same phone can scan again straight away, and a fresh processor maps it.
    assert upload(client, code, packet(0)).status_code == 200
    fresh = RoomProcessor(state, code, Detector(), Native)
    while fresh.step():
        pass
    fresh.close()
    assert client.get(f"/v1/rooms/{code}/processing").json()["mapped"] == 1


def test_reset_unknown_room(client):
    assert client.post("/v1/rooms/00000000/reset").status_code == 404
