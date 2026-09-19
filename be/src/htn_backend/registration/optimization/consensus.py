"""Resolve initial pose ambiguity using training surfaces only; at most eight hypotheses."""

from ..rigid import difference, physical


def resolve(candidates, cloud, reference, refine):
    if not candidates:
        return None
    support, initial = candidates[0]
    fitted = refine(cloud, reference, initial)
    contenders = [pose for votes, pose in candidates[1:] if votes >= support * 0.8]
    if not contenders:
        return fitted
    transform = fitted.transformation
    if fitted.fitness < 0.45 or fitted.inlier_rmse > 0.045 or not physical(transform):
        return None
    for pose in contenders:
        check = refine(cloud, reference, pose)
        delta, angle = difference(transform, check.transformation)
        if (
            check.fitness < 0.45
            or check.inlier_rmse > 0.045
            or not physical(check.transformation)
            or delta > 0.08
            or angle > 3
        ):
            return None
    return fitted
