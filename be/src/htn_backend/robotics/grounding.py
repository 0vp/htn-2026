"""Project an explicitly selected image region into measured RGB-D geometry."""

import json

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..capture.codec import decode
from ..perception.orientation import upright_quarter_turns
from ..processing.alignment import stream_key
from ..storage.database import StoreError


class RegionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sequence: int = Field(ge=1, strict=True)
    # Coordinates relative to the upright image returned by observations/image.jpg.
    bbox: tuple[float, float, float, float]
    label: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid_box(self):
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("bbox must be normalized upright [left,top,right,bottom]")
        return self


def project_region(frame, box):
    h = frame.header
    if not frame.rgb_jpeg:
        raise StoreError(409, "Selected observation has no RGB image")
    if h.tracking != "normal":
        raise StoreError(409, "Camera tracking is not normal; geometric grounding unavailable")
    height, width = frame.depth.shape
    y, x = np.indices((height, width))
    z = frame.depth
    points = np.stack(((x - h.cx) / h.fx * z, (y - h.cy) / h.fy * z, z), axis=-1)
    if h.camera_convention == "arkit":
        points *= [1, -1, -1]
    k = upright_quarter_turns(h)
    points, depth, confidence = (np.rot90(a, k) for a in (points, z, frame.confidence))
    height, width = depth.shape
    x0, y0, x1, y1 = box
    region = np.s_[
        int(y0 * height) : int(np.ceil(y1 * height)), int(x0 * width) : int(np.ceil(x1 * width))
    ]
    depth, points, confidence = depth[region], points[region], confidence[region]
    valid = np.isfinite(depth) & (depth >= 0.15) & (depth <= 5) & (confidence >= 2)
    count = int(valid.sum())
    if count < 12:
        raise StoreError(409, "Insufficient high-confidence depth in selected region")
    values = depth[valid]
    low, median, high = np.quantile(values, [0.25, 0.5, 0.75])
    spread = float(high - low)
    if spread > 0.15 + 0.03 * median:
        raise StoreError(
            409, "Selected region spans ambiguous depths; tighten selection or reobserve"
        )
    # Reject depth outliers, without guessing hidden object shape or orientation.
    support = valid & (abs(depth - median) <= max(0.04, 1.5 * spread))
    cloud = points[support]
    if len(cloud) < 12:
        raise StoreError(409, "Selected region has too little consistent surface support")
    return dict(
        camera_surface_center_m=np.median(cloud, axis=0).tolist(),
        camera_surface_bounds_m=[cloud.min(axis=0).tolist(), cloud.max(axis=0).tolist()],
        depth_median_m=float(median),
        depth_iqr_m=spread,
        supporting_depth_pixels=len(cloud),
        depth_coverage=float(count / valid.size),
        semantic_verification=False,
        object_pose=None,
        grasp_ready=False,
        geometry_status=(
            "Measured image-region surface; background can contribute. Not an object pose."
        ),
    )


def ground(state, room_id, request):
    with state.store.lock:
        state.store.require_room(room_id)
        row = state.store.db.execute(
            "SELECT sequence,device_id,header,received_at FROM frames "
            "WHERE room_id=? AND sequence=?",
            (room_id, request.sequence),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Observation not found in this room")
        value = dict(row)
        value["header"] = json.loads(value["header"])
        frame = decode(state.store.payload(room_id, request.sequence))
        alignment = state.transforms(room_id).get(stream_key(value), {})
    result = project_region(frame, request.bbox)
    transform = alignment.get("room_from_local")
    center = None
    if transform is not None:
        pose = np.array(transform).reshape(4, 4, order="F") @ np.array(
            frame.header.camera_to_world
        ).reshape(4, 4, order="F")
        center = (pose @ np.array([*result["camera_surface_center_m"], 1]))[:3].tolist()
    return dict(
        **result,
        sequence=request.sequence,
        candidate_label=request.label,
        label_source="agent proposal; not verified by depth",
        bbox_upright=request.bbox,
        room_surface_center_m=center,
        coordinate_system="right_handed_y_up_meters",
        camera_convention=frame.header.camera_convention,
        pose_source="registered capture pose; not loop-corrected or calibrated to robot",
        capture_timestamp_s=frame.header.timestamp_s,
        received_at=row["received_at"],
        requires_reobservation=True,
    )
