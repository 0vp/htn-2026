"""Approximate WGS84 context, never used by SLAM or robot navigation."""

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeographicPose(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    timestamp_unix_s: float = Field(ge=0)
    pose_timestamp_s: float = Field(ge=0)
    pose_time_offset_s: float = Field(ge=-0.35, le=0.35)
    camera_to_world: tuple[float, ...] = Field(min_length=16, max_length=16)

    @model_validator(mode="after")
    def rigid_pose(self):
        t = np.array(self.camera_to_world).reshape(4, 4, order="F")
        r = t[:3, :3]
        if not (
            np.allclose(t[3], [0, 0, 0, 1], atol=1e-5)
            and np.allclose(r.T @ r, np.eye(3), atol=1e-3)
            and np.isclose(np.linalg.det(r), 1, atol=1e-3)
            and np.max(np.abs(t[:3, 3])) <= 10000
        ):
            raise ValueError("geographic pose must be a rigid local metre transform")
        return self


class GeographicHeading(GeographicPose):
    degrees: float = Field(ge=0, lt=360)
    accuracy_degrees: float = Field(ge=0, le=180)
    reference: Literal["true_north", "magnetic_north"]
    orientation: Literal["landscape_right"] = "landscape_right"
    # World direction of the top edge in the declared heading orientation.
    reference_direction_world: tuple[float, float, float]

    @model_validator(mode="after")
    def unit_direction(self):
        if not np.isclose(np.linalg.norm(self.reference_direction_world), 1, atol=1e-3):
            raise ValueError("heading reference must be a unit direction")
        return self


class GeographicAnchor(GeographicPose):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    horizontal_accuracy_m: float = Field(ge=0)
    heading: GeographicHeading | None = None


def improves(new: GeographicAnchor, old: GeographicAnchor) -> bool:
    """Keep one coherent measurement per stream; reject delayed/degraded updates."""
    if new.timestamp_unix_s <= old.timestamp_unix_s:
        return False
    if new.horizontal_accuracy_m > old.horizontal_accuracy_m:
        return False
    a, b = new.heading, old.heading
    if b and (
        not a
        or (b.reference == "true_north" and a.reference != "true_north")
        or a.accuracy_degrees > b.accuracy_degrees
    ):
        return False
    return (
        new.horizontal_accuracy_m < old.horizontal_accuracy_m
        and new.horizontal_accuracy_m <= old.horizontal_accuracy_m * 0.8
    ) or bool(
        a
        and (
            not b
            or (
                a.accuracy_degrees < b.accuracy_degrees
                and a.accuracy_degrees <= b.accuracy_degrees * 0.8
            )
            or (a.reference == "true_north" and b.reference != "true_north")
        )
    )
