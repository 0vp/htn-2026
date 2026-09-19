"""Verify metric projection and image orientation, not semantic object identity."""

from dataclasses import replace

import numpy as np
import pytest
from conftest import packet, room, upload

from htn_backend.capture.codec import decode
from htn_backend.capture.frame import Frame
from htn_backend.perception.orientation import upright_quarter_turns
from htn_backend.robotics.grounding import project_region
from htn_backend.storage.database import StoreError


@pytest.mark.parametrize("turn", range(4))
def test_all_upright_rotations_preserve_camera_metric_coordinates(turn):
    base = decode(packet())
    theta = turn * np.pi / 2
    c, s = np.cos(theta), np.sin(theta)
    pose = np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    h = base.header.model_copy(
        update=dict(
            depth_width=30,
            depth_height=20,
            fx=30,
            fy=30,
            cx=15,
            cy=10,
            camera_to_world=tuple(pose.flatten(order="F")),
        )
    )
    frame = Frame(
        h, np.full((20, 30), 2, dtype="f4"), np.full((20, 30), 2, dtype="u1"), base.rgb_jpeg
    )
    box = (0.1, 0.2, 0.5, 0.6)
    result = project_region(frame, box)
    k = upright_quarter_turns(h)
    mask = np.zeros(np.rot90(frame.depth, k).shape, dtype=bool)
    height, width = mask.shape
    mask[
        int(0.2 * height) : int(np.ceil(0.6 * height)), int(0.1 * width) : int(np.ceil(0.5 * width))
    ] = True
    y, x = np.where(np.rot90(mask, -k))
    expected = np.stack(((x - 15) / 30 * 2, -(y - 10) / 30 * 2, np.full(len(x), -2)), axis=1)
    np.testing.assert_allclose(result["camera_surface_center_m"], np.median(expected, axis=0))
    assert result["depth_median_m"] == 2
    assert not result["grasp_ready"] and result["object_pose"] is None


def test_missing_and_ambiguous_depth_fail_instead_of_inventing_location():
    frame = decode(packet())
    with pytest.raises(StoreError, match="Insufficient"):
        project_region(replace(frame, confidence=np.zeros((4, 4), dtype="u1")), (0, 0, 1, 1))
    depth = np.ones((4, 4), dtype="f4")
    depth[2:] = 4
    with pytest.raises(StoreError, match="ambiguous"):
        project_region(replace(frame, depth=depth), (0, 0, 1, 1))


def test_ground_endpoint_scopes_sequence_and_does_not_claim_semantic_verification(client):
    code = room(client)
    sequence = upload(client, code, packet()).json()["sequence"]
    body = dict(sequence=sequence, bbox=[0, 0, 1, 1], label="proposed bottle")
    response = client.post(f"/v1/rooms/{code}/observations/ground", json=body)
    assert response.status_code == 200
    result = response.json()
    assert result["camera_surface_center_m"][2] == -1
    assert result["room_surface_center_m"] is None
    assert result["semantic_verification"] is False
    other = room(client)
    assert client.post(f"/v1/rooms/{other}/observations/ground", json=body).status_code == 404
    assert (
        client.post(
            f"/v1/rooms/{code}/observations/ground", json={**body, "bbox": [-1, 0, 1, 1]}
        ).status_code
        == 422
    )
