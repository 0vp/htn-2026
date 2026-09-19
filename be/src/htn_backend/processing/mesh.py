"""Compact glTF binary mesh, meters and Y up, for native and browser viewers."""

import json
import struct

import numpy as np


def glb(vertices: np.ndarray, triangles: np.ndarray) -> bytes:
    points = np.asarray(vertices, dtype="<f4").reshape(-1, 3)
    indices = np.asarray(triangles, dtype="<u4").reshape(-1)
    if not len(points) or not len(indices):
        document = {"asset": {"version": "2.0"}, "scenes": [{"nodes": []}], "scene": 0}
        binary = b""
    else:
        binary = points.tobytes() + indices.tobytes()
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}],
            "meshes": [
                {"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}
            ],
            "materials": [
                {
                    "doubleSided": True,
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.65, 0.65, 0.65, 1],
                        "metallicFactor": 0,
                        "roughnessFactor": 1,
                    },
                }
            ],
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": points.nbytes, "target": 34962},
                {
                    "buffer": 0,
                    "byteOffset": points.nbytes,
                    "byteLength": indices.nbytes,
                    "target": 34963,
                },
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": len(points),
                    "type": "VEC3",
                    "min": points.min(0).tolist(),
                    "max": points.max(0).tolist(),
                },
                {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
            ],
        }
    header = json.dumps(document, separators=(",", ":"), allow_nan=False).encode()
    header += b" " * (-len(header) % 4)
    chunks = struct.pack("<II", len(header), 0x4E4F534A) + header
    if binary:
        chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks
