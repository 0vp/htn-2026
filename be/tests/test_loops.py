"""Relative camera transforms and corrected poses must preserve metric camera rays."""

from dataclasses import replace

import numpy as np
import pytest
from conftest import packet
from scipy.spatial.transform import Rotation

from htn_backend.capture.codec import decode
from htn_backend.mapping.hydra.packet import Y_TO_Z
from htn_backend.mapping.loops.packet import encode_edges
from htn_backend.mapping.loops.poses import corrected_frame


def make_frame():
    return decode(packet())


def test_loop_relative_camera_basis_roundtrip():
    pose = np.eye(4)
    pose[:3, :3] = Rotation.from_euler("y", 0.4).as_matrix()
    pose[:3, 3] = [0.4, 0.1, -0.2]
    edge = dict(from_timestamp_ns=100, to_timestamp_ns=10, to_T_from=pose.tolist())
    encoded = encode_edges([edge])[0]
    basis = np.diag([1, -1, -1, 1])
    np.testing.assert_allclose(basis @ np.array(encoded["to_T_from"]) @ basis, pose)
    with pytest.raises(ValueError):
        encode_edges([edge | {"from_timestamp_ns": 5}])
    pose[0, 0] = 2
    with pytest.raises(ValueError):
        encode_edges([edge | {"to_T_from": pose.tolist()}])


def test_visibility_uses_exact_optimized_pose_or_defers():
    frame = make_frame()
    frame = replace(frame, header=frame.header.model_copy(update={"camera_convention": "arkit"}))
    native = np.eye(4)
    native[:3, :3] = Y_TO_Z @ np.diag([1, -1, -1])
    native[:3, 3] = Y_TO_Z @ [0.2, 0.1, 0.3]
    q = Rotation.from_matrix(native[:3, :3]).as_quat()
    row = [frame.header.timestamp_s, *native[:3, 3], *q[[3, 0, 1, 2]]]
    corrected = corrected_frame(frame, np.array([row]))
    pose = np.array(corrected.header.camera_to_world).reshape(4, 4, order="F")
    np.testing.assert_allclose(pose[:3, :3], np.eye(3), atol=1e-12)
    np.testing.assert_allclose(pose[:3, 3], [0.2, 0.1, 0.3])
    row[0] -= 0.01
    assert corrected_frame(frame, np.array([row])) is None


@pytest.mark.parametrize("gap_s", [0.2, 1.0])
def test_loop_endpoints_are_adjusted_to_real_native_keyframes(gap_s):
    from htn_backend.mapping.loops.anchors import NativeAnchors

    anchors = NativeAnchors()
    poses = {}
    for stamp, x in [(10.0, 0.0), (10.0 + gap_s, 0.2), (20.0, 1.0), (20.0 + gap_s, 1.2)]:
        f = make_frame()
        pose = np.eye(4)
        pose[0, 3] = x
        poses[stamp] = pose
        anchors.observe(
            replace(
                f,
                header=f.header.model_copy(
                    update=dict(timestamp_s=stamp, camera_to_world=tuple(pose.flatten(order="F")))
                ),
            )
        )
    anchors.update([[10.0], [20.0]])
    relative = np.linalg.inv(poses[10.0 + gap_s]) @ poses[20.0 + gap_s]
    relative[0, 3] -= 0.3
    result = anchors.resolve(
        [
            dict(
                from_timestamp_ns=round((20.0 + gap_s) * 1e9),
                to_timestamp_ns=round((10.0 + gap_s) * 1e9),
                to_T_from=relative.tolist(),
                verified_from_ns=[20_000_000_000],
                verified_to_ns=[10_000_000_000],
            )
        ]
    )
    assert len(result) == 1
    assert result[0]["from_timestamp_ns"] == 20_000_000_000
    assert result[0]["to_timestamp_ns"] == 10_000_000_000
    assert np.asarray(result[0]["to_T_from"])[0, 3] == pytest.approx(0.7)


def test_unverified_distant_anchor_is_not_used():
    from htn_backend.mapping.loops.anchors import NativeAnchors

    anchors = NativeAnchors()
    for stamp, x in [(10.0, 0.0), (20.0, 1.0), (21.0, 2.0)]:
        f = make_frame()
        pose = np.eye(4)
        pose[0, 3] = x
        anchors.observe(
            replace(
                f,
                header=f.header.model_copy(
                    update=dict(timestamp_s=stamp, camera_to_world=tuple(pose.flatten(order="F")))
                ),
            )
        )
    anchors.update([[10.0], [20.0]])
    assert not anchors.resolve(
        [
            dict(
                from_timestamp_ns=21_000_000_000,
                to_timestamp_ns=10_000_000_000,
                to_T_from=np.eye(4).tolist(),
            )
        ]
    )
