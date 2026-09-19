"""Geometry proposal with independent geometry and appearance evidence before fusion."""

import time

import numpy as np
from scipy.spatial import cKDTree

from .features import Keyframe
from .geometry import estimate, prepare
from .rigid import difference, physical, residuals


def register(source: list[Keyframe], target: list[Keyframe], match) -> dict:
    from .optimization.matches import prefetch

    started = time.perf_counter()

    def answer(status, **values):
        return {
            "status": status,
            "method": "fpfh_ransac_icp_rgbd_checks",
            "latency_ms": (time.perf_counter() - started) * 1000,
            **values,
        }

    if min(len(source), len(target)) < 5:
        return answer("need_more_views")
    from .visual_seed import propose

    visual = propose(source, target, match=match)
    if visual is not None:
        return visual | {"latency_ms": (time.perf_counter() - started) * 1000}
    from .verification.partial import register as partial_register

    partial = partial_register(source, target, match)
    if partial is not None:
        return partial | {"latency_ms": (time.perf_counter() - started) * 1000}
    train_a, train_b = prepare(source[:-2]), prepare(target[:-2])
    candidates = [estimate(train_a, train_b, seed=seed) for seed in (31, 67)]
    candidates.sort(key=lambda x: x["fitness"], reverse=True)
    best = candidates[0]
    transform = best["transform"]
    if best["fitness"] < 0.55 or best["rmse"] > 0.045 or not physical(transform):
        return answer("weak_geometry", fit_overlap=best["fitness"])
    delta, angle = difference(transform, candidates[1]["transform"])
    if candidates[1]["fitness"] > 0.8 * best["fitness"] and (delta > 0.15 or angle > 5):
        return answer("ambiguous_geometry")
    # Entire frames on both sides are excluded from proposal generation and ICP.
    check_a, check_b = prepare(source[-2:]), prepare(target[-2:])
    check = estimate(check_a, check_b, seed=107)
    delta, angle = difference(transform, check["transform"])
    if check["fitness"] < 0.45 or delta > 0.12 or angle > 5:
        return answer(
            "independent_geometry_disagreement",
            translation_disagreement_m=delta,
            rotation_disagreement_deg=angle,
            check_overlap=check["fitness"],
        )
    points_a, points_b = np.asarray(check_a[0].points), np.asarray(check_b[0].points)
    moved = points_a @ transform[:3, :3].T + transform[:3, 3]
    distances, indices = cKDTree(points_b).query(moved)
    reverse = cKDTree(moved).query(points_b)[0]
    overlap = min(float(np.mean(distances < 0.1)), float(np.mean(reverse < 0.1)))
    if overlap < 0.45:
        return answer("insufficient_surface_overlap", overlap=overlap)
    # Point-to-plane observability: flat walls cannot constrain translation along the wall.
    mask = distances < 0.08
    p = moved[mask]
    n = np.asarray(check_b[0].normals)[indices[mask]]
    centered = p - p.mean(0)
    jacobian = np.column_stack([np.cross(centered, n), n])
    spectrum = np.linalg.eigvalsh(jacobian.T @ jacobian / max(1, len(p)))
    condition = float(max(0, spectrum[0]) / max(spectrum[-1], 1e-12))
    if condition < 0.002:
        return answer("degenerate_surfaces", observability=condition)
    prefetch(match, source, target)
    pairs = [match(a, b) for a in source for b in target]
    pairs = [pair for pair in pairs if len(pair[0])]
    if not pairs:
        return answer("need_visual_confirmation")
    a, b = (np.concatenate([pair[i] for pair in pairs]) for i in (0, 1))
    errors = residuals(a, b, transform)
    mask = errors < 0.10
    unique = len(np.unique(np.floor(a[mask] / 0.08).astype(int), axis=0))
    if mask.sum() < 16 or mask.mean() < 0.3 or unique < 10:
        return answer("visual_disagreement", visual_matches=len(a), visual_inliers=int(mask.sum()))
    # In a truly symmetric room geometry alone is insufficient; require distributed
    # RGB-depth support rather than silently interpreting a repeated wall as a place ID.
    return answer(
        "aligned",
        room_from_local=transform.flatten(order="F").tolist(),
        fit_overlap=best["fitness"],
        check_overlap=overlap,
        fit_rmse_m=best["rmse"],
        observability=condition,
        translation_disagreement_m=delta,
        rotation_disagreement_deg=angle,
        visual_matches=len(a),
        visual_inliers=int(mask.sum()),
        visual_rmse_m=float(np.sqrt(np.mean(errors[mask] ** 2))),
        evidence="Independent held-out geometry plus measured RGB-depth correspondences",
    )
