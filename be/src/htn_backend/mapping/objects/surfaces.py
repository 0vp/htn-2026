"""Bounded measured samples for temporal visibility, never inferred box corners."""

import json

import numpy as np

from ..hydra.packet import Y_TO_Z


def samples(result):
    vertices = np.asarray(result["vertices"])
    surfaces = {}
    for node in json.loads(str(result["nodes"])):
        indices = np.asarray(node["attributes"]["mesh_connections"], dtype=int)
        if indices.size == 0:
            continue
        if indices.min() < 0 or indices.max() >= len(vertices):
            raise ValueError("object references missing measured surface")
        indices = indices[np.linspace(0, len(indices) - 1, min(len(indices), 512), dtype=int)]
        surfaces[str(node["id"])] = vertices[indices] @ Y_TO_Z
    return surfaces
