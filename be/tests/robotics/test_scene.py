"""Agent observations preserve room isolation, clocks, calibration and uncertainty."""

import json
import time

from conftest import packet, room, upload

from htn_backend.processing.state import ProcessingState


def publish(client, code, objects=None):
    state = ProcessingState(client.app.state.store)
    state.publish(code, b"large mesh placeholder", objects or [], {"backend": "hydra"}, [])
    return state


def test_scene_before_mapping_and_images_are_independent(client):
    code = room(client)
    scene = client.get(f"/v1/rooms/{code}/scene").json()
    assert scene["revision"] == 0 and scene["observation"] is None
    assert scene["capabilities"]["navigate"] is False
    seq = upload(client, code, packet(timestamp=123)).json()["sequence"]
    scene = client.get(f"/v1/rooms/{code}/scene").json()
    observation = scene["observation"]
    assert observation["sequence"] == seq
    assert observation["capture_timestamp_s"] == 123
    assert observation["capture_age_s"] is None
    assert observation["receipt_age_s"] < 5
    assert observation["robot_pose"] is None and observation["room_from_camera"] is None
    response = client.get(observation["image_url"])
    assert response.status_code == 200 and response.content.startswith(b"\xff\xd8")
    assert (
        client.get(
            observation["image_url"], headers={"If-None-Match": response.headers["etag"]}
        ).status_code
        == 304
    )
    other = room(client)
    assert client.get(f"/v1/rooms/{other}/observations/{seq}/image.jpg").status_code == 404


def test_scene_does_not_read_mesh_or_invent_object_freshness(client):
    code = room(client)
    state = publish(client, code, [{"object_id": "a", "label": "bottle"}])
    statements = []
    state.store.db.set_trace_callback(statements.append)
    scene = client.get(f"/v1/rooms/{code}/scene").json()
    obj = scene["objects"][0]
    assert obj["confirmation_receipt_age_s"] is None
    assert not obj["grasp_ready"] and obj["requires_reobservation"]
    assert not any("SELECT * FROM maps" in s for s in statements)
    assert not any("SELECT mesh" in s for s in statements)
    assert "mesh" not in state.snapshot(code, include_mesh=False)
    assert state.snapshot(code)["mesh"] == b"large mesh placeholder"
    state.store.db.set_trace_callback(None)


def test_confirmation_age_does_not_reset_when_map_republishes(client):
    code = room(client)
    objects = [
        {"object_id": "b", "label": "bottle", "last_confirmed_received_at": time.time() - 100}
    ]
    publish(client, code, objects)
    publish(client, code, objects)
    scene = client.get(f"/v1/rooms/{code}/scene").json()
    assert scene["map_publication_age_s"] < 5
    assert scene["objects"][0]["confirmation_receipt_age_s"] >= 100
    found = client.get(f"/v1/rooms/{code}/scene/search", params={"q": "bottle"}).json()
    assert found["revision"] == 2 and found["objects"][0]["object_id"] == "b"
    assert found["search"] == "sqlite_fts5"


def test_observation_pose_uses_registered_origin_and_device_scope(client):
    code = room(client)
    upload(client, code, packet())
    state = ProcessingState(client.app.state.store)
    state.align(
        code,
        json.dumps(["phone-a", "capture-a", 0], separators=(",", ":")),
        {
            "room_from_local": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, 4, 1],
            "status": "aligned",
        },
    )
    observed = client.get(f"/v1/rooms/{code}/observations/latest").json()
    assert [r[3] for r in observed["room_from_camera"][:3]] == [2, 3, 4]
    assert (
        client.get(
            f"/v1/rooms/{code}/observations/latest", params={"device_id": "other-phone"}
        ).status_code
        == 409
    )
