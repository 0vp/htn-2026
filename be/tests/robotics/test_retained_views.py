"""Raw cleanup must preserve inspectable reference views without double transforms."""

import json
from dataclasses import replace

import numpy as np
from conftest import packet, room, upload

from htn_backend.capture.codec import decode
from htn_backend.processing.atlas.references import References
from htn_backend.processing.state import ProcessingState


def test_retained_view_can_be_observed_and_grounded_after_cleanup(client):
    code = room(client)
    payload = packet(timestamp=321)
    sequence = upload(client, code, payload).json()["sequence"]
    state = ProcessingState(client.app.state.store)
    pose = np.eye(4)
    pose[:3, 3] = [2, 3, 4]
    state.align(
        code,
        json.dumps(["phone-a", "capture-a", 0], separators=(",", ":")),
        {"status": "aligned", "room_from_local": pose.flatten(order="F").tolist()},
    )
    frame = decode(payload)
    reference = replace(
        frame,
        header=frame.header.model_copy(update={"camera_to_world": tuple(pose.flatten(order="F"))}),
    )
    References(state.store, code).save(sequence, reference)
    with state.store.lock, state.store.db:
        state.store.db.execute("UPDATE frames SET payload=x'' WHERE sequence=?", (sequence,))
    # Raw-download contract remains 410; reference inspection is a separate explicit source.
    assert client.get(f"/v1/rooms/{code}/frames/{sequence}").status_code == 410
    observation = client.get(f"/v1/rooms/{code}/observations/latest").json()
    assert observation["storage_source"] == "retained_reference"
    assert observation["capture_timestamp_s"] == 321
    np.testing.assert_allclose(observation["room_from_camera"], pose)
    assert client.get(observation["image_url"]).status_code == 200
    history = client.get(f"/v1/rooms/{code}/observations/history").json()
    assert [v["sequence"] for v in history["views"]] == [sequence]
    assert (
        client.get(f"/v1/rooms/{code}/observations/history", params={"before": sequence}).json()[
            "views"
        ]
        == []
    )
    result = client.post(
        f"/v1/rooms/{code}/observations/ground",
        json={"sequence": sequence, "bbox": [0, 0, 1, 1], "label": "surface"},
    ).json()
    np.testing.assert_allclose(result["room_surface_center_m"], [1.75, 3.25, 3])
    assert not result["grasp_ready"]
    other = room(client)
    assert client.get(f"/v1/rooms/{other}/observations/{sequence}").status_code == 404
    assert client.get(f"/v1/rooms/{other}/observations/history").json()["views"] == []


def test_raw_cleanup_without_reference_fails_explicitly(client):
    code = room(client)
    sequence = upload(client, code, packet()).json()["sequence"]
    store = client.app.state.store
    with store.lock, store.db:
        store.db.execute("UPDATE frames SET payload=x'' WHERE sequence=?", (sequence,))
    result = client.get(f"/v1/rooms/{code}/observations/{sequence}")
    assert result.status_code == 410 and "no reference" in result.json()["detail"]
