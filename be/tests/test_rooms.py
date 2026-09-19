"""Room isolation, durable receipts and restart behavior."""

from concurrent.futures import ThreadPoolExecutor

from conftest import packet, room, upload
from fastapi.testclient import TestClient

from htn_backend.main import create_app


def test_store_retry_and_conflict(client):
    code = room(client)
    data = packet()
    first = upload(client, code, data).json()
    assert first["stored"] and not first["duplicate"]
    again = upload(client, code, data).json()
    assert again["duplicate"] and again["sequence"] == first["sequence"]
    assert upload(client, code, packet(timestamp=2)).status_code == 409
    result = client.get(f"/v1/rooms/{code}").json()
    assert result["frames_stored"] == 1 and result["bytes_stored"] == len(data)
    assert client.get(f"/v1/rooms/{code}/frames/{first['sequence']}").content == data


def test_independent_phones_epochs_and_delayed_frames(client):
    code = room(client)
    client.post(f"/v1/rooms/{code}/join", json={"device_id": "phone-b"})
    for device in ("phone-a", "phone-b"):
        for epoch in (0, 1):
            for index, timestamp in ((3, 1e12), (2, 0), (1, 1)):
                assert (
                    upload(client, code, packet(index, epoch, timestamp), device).status_code == 200
                )
    assert client.get(f"/v1/rooms/{code}").json()["frames_stored"] == 12


def test_unknown_room_member_and_cross_room_reads(client):
    first, second = room(client), room(client)
    result = upload(client, first, packet()).json()
    assert client.get(f"/v1/rooms/{second}/frames/{result['sequence']}").status_code == 404
    assert upload(client, first, packet(), "absent").status_code == 409
    assert client.post("/v1/rooms/FFFFFFFF/join", json={"device_id": "a"}).status_code == 404


def test_close_preserves_capture_and_retry(client):
    code = room(client)
    assert upload(client, code, packet()).status_code == 200
    assert client.post(f"/v1/rooms/{code}/close").json()["closed"]
    assert upload(client, code, packet()).json()["duplicate"]
    assert upload(client, code, packet(1)).status_code == 409
    assert client.post(f"/v1/rooms/{code}/join", json={"device_id": "b"}).status_code == 409
    assert len(client.get(f"/v1/rooms/{code}/frames").json()["frames"]) == 1


def test_pagination_and_repeated_join(client):
    code = room(client)
    for _ in range(3):
        client.post(f"/v1/rooms/{code}/join", json={"device_id": "phone-a"})
    for i in range(4):
        upload(client, code, packet(i))
    page = client.get(f"/v1/rooms/{code}/frames?limit=2").json()
    rest = client.get(f"/v1/rooms/{code}/frames?after={page['next_after']}").json()
    assert [x["header"]["frame_id"] for x in page["frames"] + rest["frames"]] == [0, 1, 2, 3]
    assert len(client.get(f"/v1/rooms/{code}").json()["devices"]) == 1


def test_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        code = room(client)
        receipt = upload(client, code, packet()).json()
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/v1/rooms/{code}").json()["frames_stored"] == 1
        assert upload(client, code, packet()).json()["duplicate"]
        assert client.get(f"/v1/rooms/{code}/frames/{receipt['sequence']}").content == packet()


def test_concurrent_idempotent_uploads(client):
    code = room(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: upload(client, code, packet()).json(), range(12)))
    assert sum(not r["duplicate"] for r in results) == 1
    assert len({r["sequence"] for r in results}) == 1


def test_room_inputs(client):
    assert client.post("/v1/rooms", json={"name": "   "}).status_code == 422
    code = room(client)
    assert client.post(f"/v1/rooms/{code}/join", json={"device_id": "../x"}).status_code == 422
    assert client.get(f"/v1/rooms/{code}/frames?limit=201").status_code == 422
