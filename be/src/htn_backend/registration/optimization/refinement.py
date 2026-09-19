"""The measured default local surface refinement; acceptance stays with the caller."""

import open3d as o3d


def refine(source, target, initial):
    reg = o3d.pipelines.registration
    return reg.registration_icp(
        source,
        target,
        0.08,
        initial,
        reg.TransformationEstimationPointToPlane(reg.TukeyLoss(0.05)),
        reg.ICPConvergenceCriteria(max_iteration=30),
    )
