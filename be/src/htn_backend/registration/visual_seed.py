"""RGB-D proposal, checked on withheld source views before merging partial scans.

Old room reference views remain fixed. Alternating new views are withheld from the
proposal and its ICP fit; both appearance and measured surfaces must agree on them.
"""

import numpy as np
from scipy.spatial import cKDTree

from .geometry import prepare_cloud
from .optimization.consensus import resolve
from .optimization.matches import prefetch
from .optimization.references import select_references
from .optimization.refinement import refine
from .rigid import difference, hypotheses, physical, residuals


def matches(source, target, match):
    prefetch(match, source, target)
    pairs = [match(a, b) for a in source for b in target]
    pairs = [p for p in pairs if len(p[0])]
    if not pairs:
        return np.empty((0, 3)), np.empty((0, 3))
    return tuple(np.concatenate([p[i] for p in pairs]) for i in (0, 1))


def visual_evidence(a, b, transform):
    errors = residuals(a, b, transform)
    mask = errors < 0.10
    return {
        "inliers": int(mask.sum()),
        "fraction": float(mask.mean()) if len(mask) else 0.0,
        "cells": len(np.unique(np.floor(a[mask] / 0.08), axis=0)),
        "rmse_m": float(np.sqrt(np.mean(errors[mask] ** 2))) if mask.any() else 1.0,
    }


def propose(source, target, match):
    if min(len(source), len(target)) < 5:
        return None
    train, heldout = source[::2], source[1::2]
    available_references = len(target)
    target = select_references(train, target, match)
    a, b = matches(train, target, match)
    candidates = hypotheses(a, b)
    if not candidates:
        return None
    support, initial = candidates[0]
    train_cloud, check_cloud, reference = (prepare_cloud(v) for v in (train, heldout, target))
    fitted = resolve(candidates, train_cloud, reference, refine)
    if fitted is None:
        return None
    check = refine(check_cloud, reference, initial)
    transform = fitted.transformation
    delta, angle = difference(transform, check.transformation)
    shift, rotation = difference(initial, transform)
    if (
        min(fitted.fitness, check.fitness) < 0.45
        or max(fitted.inlier_rmse, check.inlier_rmse) > 0.045
        or not physical(transform)
        or shift > 0.10
        or rotation > 3
        or delta > 0.08
        or angle > 3
    ):
        return None
    train_visual = visual_evidence(a, b, transform)
    check_a, check_b = matches(heldout, target, match)
    check_visual = visual_evidence(check_a, check_b, transform)
    if (
        train_visual["inliers"] < 12
        or train_visual["cells"] < 8
        or check_visual["inliers"] < 8
        or check_visual["cells"] < 6
        or min(train_visual["fraction"], check_visual["fraction"]) < 0.3
        or max(train_visual["rmse_m"], check_visual["rmse_m"]) > 0.07
    ):
        return None
    # Verify the proposal on withheld measured geometry, not the refitted check transform.
    points = np.asarray(check_cloud.points) @ transform[:3, :3].T + transform[:3, 3]
    reference_points = np.asarray(reference.points)
    distances, indices = cKDTree(reference_points).query(points)
    overlap = min(
        float(np.mean(distances < 0.1)),
        float(np.mean(cKDTree(points).query(reference_points)[0] < 0.1)),
    )
    if overlap < 0.45:
        return None
    mask = distances < 0.08
    p = points[mask]
    normals = np.asarray(reference.normals)[indices[mask]]
    jacobian = np.column_stack([np.cross(p - p.mean(0), normals), normals])
    spectrum = np.linalg.eigvalsh(jacobian.T @ jacobian / max(1, len(p)))
    condition = float(max(0, spectrum[0]) / max(spectrum[-1], 1e-12))
    if condition < 0.002:
        return None
    return dict(
        status="aligned",
        method="rgbd_seed_icp_withheld_views",
        room_from_local=transform.flatten(order="F").tolist(),
        reference_views=len(target),
        available_reference_views=available_references,
        fit_overlap=fitted.fitness,
        check_overlap=overlap,
        fit_rmse_m=fitted.inlier_rmse,
        observability=condition,
        translation_disagreement_m=delta,
        rotation_disagreement_deg=angle,
        training_visual=train_visual,
        withheld_visual=check_visual,
        evidence="RGB-D proposal; separate new capture views verify appearance and geometry",
    )
