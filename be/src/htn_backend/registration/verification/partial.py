"""Verify partial overlap using independently captured, pair-supported surfaces."""

import numpy as np
from scipy.spatial import cKDTree

from ..geometry import prepare_cloud
from ..optimization.matches import prefetch
from ..optimization.pairwise import proposals, supported
from ..optimization.refinement import refine
from ..rigid import difference, physical
from .visibility import visible_reference


def cloud(pairs, index):
    return prepare_cloud(list({id(pair[index]): pair[index] for pair in pairs}.values()))


def surface_evidence(source, target, transform):
    points = np.asarray(source.points) @ transform[:3, :3].T + transform[:3, 3]
    reference = np.asarray(target.points)
    if min(len(points), len(reference)) < 100:
        return 0.0, 0.0
    distances, indices = cKDTree(reference).query(points)
    overlap = min(
        float(np.mean(distances < 0.1)), float(np.mean(cKDTree(points).query(reference)[0] < 0.1))
    )
    mask = distances < 0.08
    if mask.sum() < 100:
        return overlap, 0.0
    p, normals = points[mask], np.asarray(target.normals)[indices[mask]]
    jacobian = np.column_stack([np.cross(p - p.mean(0), normals), normals])
    spectrum = np.linalg.eigvalsh(jacobian.T @ jacobian / len(p))
    return overlap, float(max(0, spectrum[0]) / max(spectrum[-1], 1e-12))


def propose(source, target, match):
    if min(len(source), len(target)) < 5:
        return None
    train, heldout = source[::2], source[1::2]
    prefetch(match, source, target)
    pairs = [(a, b, *match(a, b)) for a in train for b in target]
    checks = [(a, b, *match(a, b)) for a in heldout for b in target]
    accepted = []
    for votes, initial in proposals(pairs)[:4]:
        training, validation = supported(pairs, initial), supported(checks, initial)
        # Separate camera views, not duplicated correspondences, provide validation.
        if any(
            len({id(p[i]) for p in rows}) < 2 for rows in (training, validation) for i in (0, 1)
        ):
            continue
        source_cloud, reference = cloud(training, 0), cloud(training, 1)
        check_cloud, check_reference = cloud(validation, 0), cloud(validation, 1)
        fitted = refine(source_cloud, reference, initial)
        check = refine(check_cloud, check_reference, initial)
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
            continue
        # Recheck the original held-out pairs after training-only refinement.
        if len(supported(validation, transform)) != len(validation):
            continue
        visible = visible_reference(
            check_reference, list({id(p[0]): p[0] for p in validation}.values()), transform
        )
        overlap, condition = surface_evidence(check_cloud, visible, transform)
        if overlap < 0.45 or condition < 0.002:
            continue
        accepted.append(
            (
                votes,
                transform,
                dict(
                    status="aligned",
                    method="pair_consensus_withheld_rgbd",
                    room_from_local=transform.flatten(order="F").tolist(),
                    training_pairs=len(training),
                    withheld_pairs=len(validation),
                    withheld_views=len({id(p[0]) for p in validation}),
                    fit_overlap=fitted.fitness,
                    check_overlap=overlap,
                    fit_rmse_m=fitted.inlier_rmse,
                    observability=condition,
                    translation_disagreement_m=delta,
                    rotation_disagreement_deg=angle,
                    evidence="Independent image-pair consensus and withheld measured surfaces",
                ),
            )
        )
    if not accepted:
        return None
    votes, pose, result = accepted[0]
    for other_votes, other, _ in accepted[1:]:
        delta, angle = difference(pose, other)
        if other_votes >= votes * 0.8 and (delta > 0.08 or angle > 3):
            return None
    return result


def register(source, target, match):
    """Try both view partitions; require agreement when both provide evidence."""
    forward = propose(source, target, match)
    reverse = propose(target, source, match)
    if reverse is not None:
        inverse = np.linalg.inv(np.array(reverse["room_from_local"]).reshape(4, 4, order="F"))
        if forward is not None:
            pose = np.array(forward["room_from_local"]).reshape(4, 4, order="F")
            delta, angle = difference(pose, inverse)
            if delta > 0.08 or angle > 3:
                return None
            forward["cycle_translation_m"] = delta
            forward["cycle_rotation_deg"] = angle
        else:
            forward = reverse | {
                "room_from_local": inverse.flatten(order="F").tolist(),
                "validation_direction": "target_to_source",
            }
    return forward
