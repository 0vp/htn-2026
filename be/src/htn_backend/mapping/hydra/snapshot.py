"""Hydra owns geometry and object identity; this only adapts viewer coordinates."""

import json

import numpy as np

from ..bounds import fit_upright_bounds
from .config import LABELS
from .packet import Y_TO_Z


def snapshot(result, version, integrated_frames=None):
    vertices = np.asarray(result["vertices"], dtype=np.float32)
    triangles = np.asarray(result["triangles"], dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("invalid Hydra vertices")
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("invalid Hydra faces")
    if triangles.size and (triangles.min() < 0 or triangles.max() >= len(vertices)):
        raise ValueError("Hydra faces reference missing vertices")
    vertices = vertices @ Y_TO_Z
    objects = []
    for node in json.loads(str(result["nodes"])):
        a = node["attributes"]
        label_id = a["semantic_label"]
        if not 0 <= label_id < len(LABELS):
            raise ValueError("invalid Hydra semantic label")
        indices = np.array(a["mesh_connections"], dtype=int)
        if not len(indices):
            continue
        if indices.min() < 0 or indices.max() >= len(vertices):
            raise ValueError("Hydra object references missing mesh vertices")
        center, extent, yaw = fit_upright_bounds(vertices[indices])
        objects.append(
            dict(
                object_id=str(node["id"]),
                label=LABELS[label_id],
                score=None,
                center_m=center.tolist(),
                size_m=extent.tolist(),
                yaw_rad=yaw,
                observations=None,
                points=len(indices),
                age_s=None,
                state="mapped",
                identity_status="hydra_native",
                source_devices=[],
                geometry_status="observed surface bounds; hidden shape unknown",
                extent_kind="visible_surface_estimate",
                representation="generic_category_model",
            )
        )
    return (
        vertices,
        triangles,
        version,
        0.04,
        version if integrated_frames is None else integrated_frames,
    ), objects
