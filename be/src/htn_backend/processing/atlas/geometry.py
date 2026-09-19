"""Spatial replacement of observed surface cells, preserving unseen geometry."""

import zlib

import numpy as np


def encode(triangles: np.ndarray) -> bytes:
    return zlib.compress(np.asarray(triangles, dtype="<f4").tobytes(), level=3)


def decode(data: bytes) -> np.ndarray:
    return np.frombuffer(zlib.decompress(data), dtype="<f4").reshape(-1, 3, 3).copy()


def cells(triangles: np.ndarray) -> np.ndarray:
    centers = triangles.mean(axis=1)
    return np.floor(centers / 0.04).astype("<i8")


def keys(values: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(values).view(np.dtype((np.void, values.dtype.itemsize * 3))).ravel()


def merge(old: np.ndarray, new: np.ndarray) -> np.ndarray:
    if not len(old):
        return new.copy()
    if not len(new):
        return old.copy()
    # Replace only cells measured by this segment. Absence of a triangle is not
    # evidence of free space, so unseen walls from previous segments remain.
    keep = ~np.isin(keys(cells(old)), keys(cells(new)))
    return np.concatenate([old[keep], new])


def tiles(vertices: np.ndarray, faces: np.ndarray) -> dict[str, np.ndarray]:
    if not len(faces):
        return {}
    triangles = np.asarray(vertices, dtype="f4")[faces]
    groups = np.floor(triangles.mean(axis=1)).astype("i8")
    unique, labels = np.unique(groups, axis=0, return_inverse=True)
    order = np.argsort(labels, kind="stable")
    boundaries = np.flatnonzero(np.diff(labels[order])) + 1
    return {
        ",".join(map(str, xyz)): triangles[indices]
        for xyz, indices in zip(unique, np.split(order, boundaries), strict=True)
    }


def mesh(groups: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    if not groups:
        return np.empty((0, 3), dtype="f4"), np.empty((0, 3), dtype="i4")
    triangles = np.concatenate(list(groups.values()))
    vertices, indices = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
    return vertices.astype("f4"), indices.reshape(-1, 3).astype("i4")
