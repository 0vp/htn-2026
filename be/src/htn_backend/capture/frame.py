"""Explicit camera and timing conventions shared by file replay and HTTP."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrameHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    version: Literal[1] = 1
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    epoch: int = Field(ge=0, le=2**31 - 1, strict=True)
    frame_id: int = Field(ge=0, le=2**53 - 1, strict=True)
    timestamp_s: float = Field(ge=0)
    tracking: Literal["normal", "limited", "unavailable"]
    camera_convention: Literal["arkit", "opencv"]
    depth_width: int = Field(ge=1, le=1024, strict=True)
    depth_height: int = Field(ge=1, le=1024, strict=True)
    rgb_width: int = Field(ge=0, le=4096, strict=True)
    rgb_height: int = Field(ge=0, le=4096, strict=True)
    rgb_bytes: int = Field(ge=0, le=8_000_000, strict=True)
    # Intrinsics already scaled to the native, unrotated depth grid.
    fx: float = Field(gt=0)
    fy: float = Field(gt=0)
    cx: float
    cy: float
    # Column-major T_world_camera, meters, camera basis declared above.
    camera_to_world: tuple[float, ...] = Field(min_length=16, max_length=16)

    @model_validator(mode="after")
    def validate_geometry(self) -> "FrameHeader":
        transform = np.array(self.camera_to_world).reshape(4, 4, order="F")
        rotation = transform[:3, :3]
        if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-5):
            raise ValueError("camera_to_world must be affine")
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3):
            raise ValueError("camera_to_world rotation must be orthonormal")
        if not np.isclose(np.linalg.det(rotation), 1, atol=1e-3):
            raise ValueError("camera_to_world must be right handed")
        if np.max(np.abs(transform[:3, 3])) > 10_000:
            raise ValueError("translation exceeds room-mapping bounds")
        if bool(self.rgb_bytes) != bool(self.rgb_width and self.rgb_height):
            raise ValueError("RGB dimensions and byte length must agree")
        if not self.rgb_bytes and (self.rgb_width or self.rgb_height):
            raise ValueError("absent RGB must have zero dimensions")
        return self


@dataclass(frozen=True)
class Frame:
    header: FrameHeader
    depth: np.ndarray
    confidence: np.ndarray
    rgb_jpeg: bytes = b""

    def __post_init__(self) -> None:
        shape = (self.header.depth_height, self.header.depth_width)
        if self.depth.shape != shape or self.confidence.shape != shape:
            raise ValueError("depth/confidence dimensions disagree with header")
        if self.depth.dtype.kind != "f":
            raise ValueError("depth must contain floating-point meters")
        if self.confidence.dtype != np.uint8 or np.any(self.confidence > 2):
            raise ValueError("confidence must be uint8 in [0, 2]")
        if len(self.rgb_jpeg) != self.header.rgb_bytes:
            raise ValueError("RGB payload length disagrees with header")
