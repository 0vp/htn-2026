"""Regression scenes exercise calibrated instances, not category connected components."""

import io
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from htn_backend.capture.frame import Frame, FrameHeader
from htn_backend.mapping.hydra.packet import Y_TO_Z
from htn_backend.perception.esam.calibration import prepare, visible_pixels
from htn_backend.perception.esam.instances import InstanceCatalog
from htn_backend.perception.orientation import upright_quarter_turns


def scene(convention="opencv"):
    image = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(image, format="JPEG")
    header = FrameHeader(
        session_id="instances",
        epoch=0,
        frame_id=0,
        timestamp_s=1,
        tracking="normal",
        camera_convention=convention,
        depth_width=16,
        depth_height=16,
        rgb_width=32,
        rgb_height=32,
        rgb_bytes=len(image.getvalue()),
        fx=16,
        fy=16,
        cx=7.5,
        cy=7.5,
        camera_to_world=tuple(np.eye(4).flatten(order="F")),
    )
    frame = Frame(
        header, np.full((16, 16), 2, dtype="f4"), np.full((16, 16), 2, dtype="u1"), image.getvalue()
    )
    y, x = np.indices((16, 16))
    points = np.stack(((x - 7.5) / 8, (y - 7.5) / 8, np.full_like(x, 2)), axis=-1)
    masks = [(x < 8) & (y < 8), (x >= 8) & (y < 8), (x < 8) & (y >= 8), (x >= 8) & (y >= 8)]
    detections = [dict(label="dining table", score=0.9, mask=mask) for mask in masks]
    result = dict(
        points=np.concatenate([points[m] for m in masks]),
        offsets=np.arange(5) * 64,
        scores=np.full(4, 0.9),
    )
    return frame, detections, result


@pytest.mark.parametrize("convention", ["arkit", "opencv"])
def test_units_and_world_axes(convention):
    frame, _, _ = scene(convention)
    pose = np.eye(4)
    pose[:3, 3] = [1, 2, 3]
    frame = replace(
        frame,
        header=frame.header.model_copy(update={"camera_to_world": tuple(pose.flatten(order="F"))}),
    )
    arrays = prepare(frame)
    assert arrays["depth_mm"][0, 0] == 2000
    assert arrays["color"].shape == (32, 32, 3)
    assert arrays["intrinsic"][0, 0] == 32
    # Optical-axis point two metres in front, with a translated phone.
    esam_world = arrays["pose"] @ [0, 0, 2, 1]
    expected = [1, 2, 1 if convention == "arkit" else 5]
    np.testing.assert_allclose(esam_world[:3] @ Y_TO_Z, expected)


def test_invalid_depth_is_not_geometry():
    frame, _, _ = scene()
    frame.depth[0, :4] = [np.nan, 0, 6, 0.1]
    frame.confidence[0, 4] = 0
    assert not prepare(frame)["depth_mm"][0, :10].any()
    frame.confidence[:] = 0
    with pytest.raises(ValueError, match="20 valid"):
        prepare(frame)


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_upright_resampling_preserves_off_axis_world_point(turns):
    frame, _, _ = scene("arkit")
    angle = turns * np.pi / 2
    c, s = np.cos(angle), np.sin(angle)
    pose = np.eye(4)
    pose[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    frame = replace(
        frame,
        header=frame.header.model_copy(update={"camera_to_world": tuple(pose.flatten(order="F"))}),
    )
    assert upright_quarter_turns(frame.header) == turns
    arrays = prepare(frame)
    u, v = 4.0, 6.0
    expected = pose[:3, :3] @ [(u - 7.5) / 8, -(v - 7.5) / 8, -2]
    u, v = (u + 0.5) * 2 - 0.5, (v + 0.5) * 2 - 0.5
    for _ in range(turns):
        u, v = v, 31 - u
    camera = np.linalg.inv(arrays["intrinsic"]) @ [u, v, 1] * 2
    actual = (arrays["pose"] @ [*camera, 1])[:3] @ Y_TO_Z
    np.testing.assert_allclose(actual, expected, atol=1e-7)


def test_four_touching_tables_remain_four_and_reordered_masks_keep_identity():
    frame, detections, result = scene()
    catalog = InstanceCatalog()
    objects, surfaces = catalog.update(frame, detections, result)
    assert len(objects) == 4
    original = {o["object_id"]: o["center_m"] for o in objects}
    assert {o["label"] for o in objects} == {"dining table"}
    assert len(surfaces) == 4
    result["points"] = np.concatenate(np.split(result["points"], 4)[::-1])
    objects, _ = catalog.update(frame, detections[::-1], result)
    assert len(objects) == 4
    assert {o["object_id"]: o["center_m"] for o in objects} == original
    assert all(o["size_m"][0] < 1.0 for o in objects)


def test_occluded_geometry_does_not_inherit_foreground_label():
    frame, detections, result = scene()
    frame.depth[:] = 1
    assert len(visible_pixels(frame, result["points"])[0]) == 0
    objects, _ = InstanceCatalog().update(frame, detections, result)
    assert objects == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("offsets", np.array([0, 64, 128, 192, 300])),
        ("offsets", np.array([0, 64, 128, 100, 256])),
        ("scores", np.array([0.9, np.nan, 0.9, 0.9])),
        ("points", np.full((256, 3), np.nan)),
    ],
)
def test_reject_invalid_worker_result(field, value):
    frame, detections, result = scene()
    result[field] = value
    with pytest.raises(ValueError, match="Invalid ESAM"):
        InstanceCatalog().update(frame, detections, result)


def test_empty_result_keeps_previously_observed_instances():
    frame, detections, result = scene()
    catalog = InstanceCatalog()
    catalog.update(frame, detections, result)
    objects, _ = catalog.update(
        frame, [], dict(points=np.empty((0, 3)), offsets=np.array([0]), scores=np.empty(0))
    )
    assert len(objects) == 4
