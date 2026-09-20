"""Top-down picture of the server's accumulated LiDAR map, with the robot and known objects.

The cloud fuses every phone frame into one room mesh (mesh.glb, metres, y up) and tracks
labelled objects. This renders that memory as an image the agent can plan routes on; the
per-frame map in perception.py stays the authority on what is near the robot right now.
"""

import io
import json
import math
import struct

import httpx
import numpy as np
from PIL import Image, ImageDraw

PIXELS_PER_M = 40


def glb_vertices(content: bytes) -> np.ndarray:
    """All POSITION vertices of an uncompressed GLB as an (N, 3) float array."""
    if content[:4] != b"glTF":
        raise ValueError("not a GLB file")
    length = struct.unpack_from("<I", content, 12)[0]
    document = json.loads(content[20 : 20 + length])
    binary = content[20 + length + 8 :]
    chunks = []
    for mesh in document.get("meshes", []):
        for primitive in mesh["primitives"]:
            accessor = document["accessors"][primitive["attributes"]["POSITION"]]
            view = document["bufferViews"][accessor["bufferView"]]
            if accessor["componentType"] != 5126 or accessor["type"] != "VEC3":
                raise ValueError("unsupported POSITION layout")
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride", 12)
            raw = np.frombuffer(
                binary, dtype=np.uint8, count=stride * accessor["count"], offset=start
            )
            chunks.append(raw.reshape(-1, stride)[:, :12].copy().view("<f4"))
    return np.concatenate(chunks) if chunks else np.zeros((0, 3), np.float32)


def render(client: httpx.Client, prefix: str, position, heading_deg) -> tuple[bytes, dict] | None:
    mesh = client.get(prefix + "/mesh.glb")
    if mesh.status_code != 200:
        return None
    vertices = glb_vertices(mesh.content)
    if len(vertices) < 100:
        return None
    ground = float(np.percentile(vertices[:, 1], 3))
    floor = vertices[vertices[:, 1] < ground + 0.08]
    walls = vertices[(vertices[:, 1] > ground + 0.15) & (vertices[:, 1] < ground + 1.8)]
    low = np.minimum(vertices[:, [0, 2]].min(0), np.array(position)) - 0.5
    high = np.maximum(vertices[:, [0, 2]].max(0), np.array(position)) + 0.5
    width, height = ((high - low) * PIXELS_PER_M).astype(int) + 1
    pixels = np.full((height, width, 3), (70, 70, 78), np.uint8)

    def place(points):
        col = ((points[:, 0] - low[0]) * PIXELS_PER_M).astype(int)
        row = ((points[:, 2] - low[1]) * PIXELS_PER_M).astype(
            int
        )  # World -z (ARKit forward) is up.
        return row.clip(0, height - 1), col.clip(0, width - 1)

    pixels[place(floor)] = (225, 225, 225)
    pixels[place(walls)] = (200, 40, 40)
    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image)
    objects = client.get(prefix + "/scene").json().get("objects", [])
    listed = []
    for item in objects[:40]:
        centre = item.get("center_m")
        if not centre:
            continue
        x, y = (centre[0] - low[0]) * PIXELS_PER_M, (centre[2] - low[1]) * PIXELS_PER_M
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(40, 90, 255), width=2)
        draw.text((x + 6, y - 6), item.get("label", "?"), fill=(40, 90, 255))
        dx, dz = centre[0] - position[0], centre[2] - position[1]
        bearing = math.degrees(math.atan2(-dx, -dz)) - heading_deg
        listed.append(
            dict(
                label=item.get("label"),
                distance_m=round(math.hypot(dx, dz), 1),
                turn_left_deg=round((bearing + 180) % 360 - 180),
            )
        )
    x, y = (position[0] - low[0]) * PIXELS_PER_M, (position[1] - low[1]) * PIXELS_PER_M
    theta = math.radians(heading_deg)
    tip = (x - math.sin(theta) * 22, y - math.cos(theta) * 22)
    draw.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(255, 210, 0))
    draw.line([x, y, *tip], fill=(255, 210, 0), width=4)
    draw.line([8, height - 10, 8 + PIXELS_PER_M, height - 10], fill=(255, 255, 255), width=2)
    draw.text((10, height - 24), "1 m", fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), dict(
        known_objects=listed, size_m=[round(float(v), 1) for v in (high - low)]
    )
