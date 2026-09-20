"""The robot's senses, from the phone riding on it: picture, LiDAR floor map, pose.

Each phone frame carries RGB, a LiDAR depth grid, intrinsics and the ARKit camera pose. From
the newest frame this builds what the agent sees (JPEG), a robot-centred top-down obstacle
map, the free distance straight ahead, and heading/position used to measure moves.
Assumes the phone is mounted in landscape looking along the robot's forward direction.
"""

import base64
import io
import math
import time
from dataclasses import dataclass

import httpx
import numpy as np
from PIL import Image, ImageDraw

from ....capture.codec import decode

CELL_M = 0.05
RANGE_M = 4.0
HALF_WIDTH_M = 0.52  # The base is 0.80 m across with the phone at its centre, plus margin.
FRESH_S = 2.5


@dataclass
class Sense:
    sequence: int
    age_s: float
    tracking: str
    heading_deg: float  # Counter-clockwise from above, ARKit world; only differences matter.
    position: tuple[float, float]  # World x, z in metres.
    clear_ahead_m: float | None  # None when LiDAR gave no usable floor/obstacle evidence.
    clear_left_m: float | None
    clear_right_m: float | None
    rgb_jpeg: bytes
    map_png: bytes
    floor_world: np.ndarray | None = None  # (N, 2) world x, z of seen floor
    obstacles_world: np.ndarray | None = None  # (N, 2) world x, z of LiDAR obstacles
    depth: np.ndarray | None = None
    header: object | None = None

    def world_point(self, x: float, y: float) -> tuple[float, float, float] | None:
        """World (x, z) and range of the surface at a picture position (0..1 from top-left)."""
        if self.depth is None or self.header is None:
            return None
        h = self.header
        u, v = x * (h.depth_width - 1), y * (h.depth_height - 1)
        r0, c0 = max(0, int(v) - 3), max(0, int(u) - 3)
        patch = self.depth[r0 : int(v) + 4, c0 : int(u) + 4]
        valid = patch[(patch > 0.15) & np.isfinite(patch)]
        if valid.size < 4:
            return None  # Glass, sky, or beyond LiDAR range (~5 m).
        d = float(np.median(valid))
        sign = -1.0 if h.camera_convention == "arkit" else 1.0
        camera = np.array([(u - h.cx) / h.fx * d, sign * (v - h.cy) / h.fy * d, sign * d, 1.0])
        pose = np.array(h.camera_to_world, dtype=np.float64).reshape(4, 4).T
        world = pose @ camera
        return float(world[0]), float(world[2]), d

    @property
    def fresh(self) -> bool:
        return self.age_s <= FRESH_S and self.tracking != "unavailable"

    def summary(self) -> dict:
        def metres(value):
            return None if value is None else round(value, 2)

        return dict(
            view_age_s=round(self.age_s, 1),
            tracking=self.tracking,
            heading_deg=round(self.heading_deg),
            clear_ahead_m=metres(self.clear_ahead_m),
            clear_left_m=metres(self.clear_left_m),
            clear_right_m=metres(self.clear_right_m),
            lidar_range_m=RANGE_M,
        )


def data_url(content: bytes, kind: str) -> dict:
    encoded = base64.b64encode(content).decode()
    return {"type": "inputImage", "imageUrl": f"data:image/{kind};base64,{encoded}"}


def _points(frame) -> tuple[np.ndarray, np.ndarray]:
    """LiDAR points in a gravity-aligned robot frame: columns right, up, forward (metres)."""
    h = frame.header
    depth = frame.depth.astype(np.float32)
    v, u = np.mgrid[0 : h.depth_height, 0 : h.depth_width]
    good = (depth > 0.15) & (depth < RANGE_M + 1) & (frame.confidence >= 1)
    d, u, v = depth[good], u[good], v[good]
    sign = -1.0 if h.camera_convention == "arkit" else 1.0  # ARKit: y up, looks along -z.
    camera = np.stack([(u - h.cx) / h.fx * d, sign * (v - h.cy) / h.fy * d, sign * d], axis=1)
    pose = np.array(h.camera_to_world, dtype=np.float64).reshape(4, 4).T  # Column-major.
    rotation = pose[:3, :3]
    world = camera @ rotation.T
    forward = rotation @ np.array([0.0, 0.0, sign])
    flat = np.array([forward[0], 0.0, forward[2]])
    flat /= np.linalg.norm(flat) or 1.0
    right = np.cross(flat, np.array([0.0, 1.0, 0.0]))
    points = np.stack([world @ right, world[:, 1], world @ flat], axis=1)
    origin = pose[:3, 3]
    ground_plane = np.stack([world[:, 0] + origin[0], world[:, 2] + origin[2]], axis=1)
    return points, pose, ground_plane


def _clearance(obstacles: np.ndarray, centre: float) -> float | None:
    lane = obstacles[np.abs(obstacles[:, 0] - centre) <= HALF_WIDTH_M]
    lane = lane[lane[:, 2] > 0.1]
    if len(lane) < 12:
        return RANGE_M
    return float(np.percentile(lane[:, 2], 2))


def _draw(floor: np.ndarray, obstacles: np.ndarray) -> bytes:
    size = int(2 * RANGE_M / CELL_M)
    scale = 3
    image = Image.new("RGB", (size, size // 2 + 12), (70, 70, 78))  # Unknown = grey.

    def cells(points):
        col = ((points[:, 0] + RANGE_M) / CELL_M).astype(int)
        row = (size // 2 - points[:, 2] / CELL_M).astype(int)
        keep = (col >= 0) & (col < size) & (row >= 0) & (row < size // 2)
        return col[keep], row[keep]

    pixels = np.array(image)
    col, row = cells(floor)
    pixels[row, col] = (225, 225, 225)  # Seen floor = free.
    col, row = cells(obstacles)
    pixels[row, col] = (200, 40, 40)  # Obstacle.
    image = Image.fromarray(pixels).resize((size * scale, (size // 2 + 12) * scale), Image.NEAREST)
    draw = ImageDraw.Draw(image)
    middle, base = size * scale // 2, size // 2 * scale
    for metres in (1, 2, 3):
        radius = metres / CELL_M * scale
        draw.arc(
            [middle - radius, base - radius, middle + radius, base + radius],
            180,
            360,
            fill=(120, 160, 255),
        )
        draw.text((middle + 4, base - radius + 2), f"{metres} m", fill=(120, 160, 255))
    half = HALF_WIDTH_M / CELL_M * scale
    draw.line([middle - half, base, middle - half, 0], fill=(90, 200, 90))
    draw.line([middle + half, base, middle + half, 0], fill=(90, 200, 90))
    draw.polygon(
        [(middle, base - 14), (middle - 9, base + 8), (middle + 9, base + 8)], fill=(255, 210, 0)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


class Senses:
    def __init__(self, client: httpx.Client, prefix: str):
        self.client, self.prefix = client, prefix

    def pose_only(self) -> tuple[float, tuple[float, float], float, str] | None:
        """(heading_deg, position, age_s, tracking) from the newest frame, or None."""
        sense = self.read(render=False)
        return (
            None
            if sense is None
            else (sense.heading_deg, sense.position, sense.age_s, sense.tracking)
        )

    def read(self, render: bool = True) -> Sense | None:
        try:
            return self._read(render)
        except (httpx.HTTPError, ValueError):
            return None  # Network hiccup or a frame that would not decode: treat as no view.

    def _read(self, render: bool) -> Sense | None:
        latest = self.client.get(self.prefix + "/observations/latest", timeout=4)
        if latest.status_code != 200:
            return None
        info = latest.json()
        if float(info.get("receipt_age_s") or 0) > 30:
            return None  # The phone stopped streaming; do not download a stale frame.
        raw = self.client.get(f"{self.prefix}/frames/{info['sequence']}", timeout=5)
        if raw.status_code != 200:
            return None
        frame = decode(raw.content)
        points, pose, ground_plane = _points(frame)
        forward = pose[:3, :3] @ np.array(
            [0.0, 0.0, -1.0 if frame.header.camera_convention == "arkit" else 1.0]
        )
        heading = math.degrees(math.atan2(-forward[0], -forward[2]))
        ahead = left = right = None
        floor = obstacles = np.zeros((0, 3))
        floor_world = obstacles_world = np.zeros((0, 2))
        if len(points) > 500:
            ground = float(np.percentile(points[:, 1], 4))
            low = points[:, 1] < ground + 0.06
            tall = (points[:, 1] > ground + 0.12) & (points[:, 1] < ground + 1.7)
            floor, obstacles = points[low], points[tall]
            floor_world, obstacles_world = ground_plane[low], ground_plane[tall]
            ahead = _clearance(obstacles, 0.0)
            left, right = _clearance(obstacles, -0.7), _clearance(obstacles, 0.7)
        return Sense(
            sequence=int(info["sequence"]),
            age_s=float(info.get("receipt_age_s") or 0.0),
            tracking=frame.header.tracking,
            heading_deg=heading,
            position=(float(pose[0, 3]), float(pose[2, 3])),
            clear_ahead_m=ahead,
            clear_left_m=left,
            clear_right_m=right,
            rgb_jpeg=frame.rgb_jpeg,
            map_png=_draw(floor, obstacles) if render else b"",
            floor_world=floor_world,
            obstacles_world=obstacles_world,
            depth=frame.depth,
            header=frame.header,
        )


def wait_fresh(senses: Senses, after_sequence: int, timeout_s: float = 3.0) -> Sense | None:
    """A frame captured after the robot stopped, so the picture matches where it now stands."""
    deadline, sense = time.monotonic() + timeout_s, None
    while time.monotonic() < deadline:
        try:
            sense = senses.read()
        except httpx.HTTPError:
            return None
        if sense is None:
            return None  # No live stream: waiting will not produce a newer picture.
        if sense and sense.sequence > after_sequence and sense.age_s < 1.5:
            return sense
        time.sleep(0.25)
    return sense
