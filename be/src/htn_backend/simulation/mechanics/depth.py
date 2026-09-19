"""Rendered RGB-D snapshots using the production image-region grounding contract.

Depth and camera extrinsics are ideal simulator measurements, not iPhone noise
or SLAM estimates. The output is visible surface support, never an object pose.
"""

import time

import numpy as np

from ...capture.frame import Frame, FrameHeader
from ...robotics.grounding import project_region
from .vision import camera_metadata


def capture(world, sequence, jpeg):
    renderer = world.renderer
    renderer.enable_depth_rendering()
    try:
        renderer.update_scene(world.data, camera="robot_pov")
        depth = renderer.render().copy()
    finally:
        renderer.disable_depth_rendering()
    height, width = depth.shape
    camera = camera_metadata(world)
    focal = height / (2 * np.tan(np.deg2rad(camera["vertical_fov_degrees"]) / 2))
    transform = np.asarray(camera["camera_to_room"])
    # OpenGL camera to OpenCV camera; project_region handles the latter directly.
    transform = transform @ np.diag([1, -1, -1, 1])
    header = FrameHeader(
        session_id="simulation",
        epoch=0,
        frame_id=sequence,
        timestamp_s=float(world.data.time),
        tracking="normal",
        camera_convention="opencv",
        depth_width=width,
        depth_height=height,
        rgb_width=width,
        rgb_height=height,
        rgb_bytes=len(jpeg),
        fx=focal,
        fy=focal,
        cx=(width - 1) / 2,
        cy=(height - 1) / 2,
        camera_to_world=tuple(transform.flatten(order="F")),
    )
    confidence = (np.isfinite(depth) & (depth >= 0.15) & (depth <= 5)).astype(np.uint8) * 2
    return Frame(header, depth, confidence, jpeg)


def ground(frame, request, received_at, current_time):
    result = project_region(frame, request.bbox)
    transform = np.asarray(frame.header.camera_to_world).reshape(4, 4, order="F")
    center = transform @ [*result["camera_surface_center_m"], 1]
    return dict(
        **result,
        sequence=request.sequence,
        candidate_label=request.label,
        label_source="agent proposal; not verified by depth",
        bbox_upright=request.bbox,
        room_surface_center_m=center[:3].tolist(),
        coordinate_system="right_handed_y_up_meters",
        camera_convention="opencv",
        pose_source="ideal simulated camera extrinsics; not SLAM",
        capture_timestamp_s=frame.header.timestamp_s,
        received_at=received_at,
        response_at=time.time(),
        age_simulation_s=max(0.0, current_time - frame.header.timestamp_s),
        storage_source="simulation_rendered_depth",
        requires_reobservation=True,
        execution_domain="simulation",
    )
