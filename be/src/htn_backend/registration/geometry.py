"""Bounded FPFH global registration, followed by local measured-surface refinement."""

import numpy as np
import open3d as o3d

from .features import Keyframe
from .optimization.refinement import refine


def prepare_cloud(keys: list[Keyframe]):
    points = np.concatenate([k.cloud for k in keys])
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    cloud = cloud.voxel_down_sample(0.07)
    if len(cloud.points) > 6000:
        cloud = cloud.select_by_index(np.linspace(0, len(cloud.points) - 1, 6000, dtype=int))
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.14, max_nn=30))
    return cloud


def prepare(keys: list[Keyframe]):
    cloud = prepare_cloud(keys)
    features = o3d.pipelines.registration.compute_fpfh_feature(
        cloud, o3d.geometry.KDTreeSearchParamHybrid(radius=0.35, max_nn=60)
    )
    return cloud, features


def estimate(source, target, method: str = "ransac", seed: int = 31) -> dict:
    reg = o3d.pipelines.registration
    a, fa = source
    b, fb = target
    if min(len(a.points), len(b.points)) < 100:
        return {"fitness": 0.0, "transform": np.eye(4), "rmse": float("inf")}
    o3d.utility.random.seed(seed)
    if method == "fgr":
        result = reg.registration_fgr_based_on_feature_matching(
            a, b, fa, fb, reg.FastGlobalRegistrationOption(maximum_correspondence_distance=0.10)
        )
    else:
        result = reg.registration_ransac_based_on_feature_matching(
            a,
            b,
            fa,
            fb,
            True,
            0.10,
            reg.TransformationEstimationPointToPoint(False),
            3,
            [
                reg.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                reg.CorrespondenceCheckerBasedOnDistance(0.1),
            ],
            reg.RANSACConvergenceCriteria(20000, 0.999),
        )
    result = refine(a, b, result.transformation)
    return {
        "fitness": result.fitness,
        "transform": result.transformation,
        "rmse": result.inlier_rmse,
    }
