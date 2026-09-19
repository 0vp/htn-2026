"""ESAM superpoints without rasterizing/transferring every full-resolution mask.

Follows the pinned upstream stream preprocessor's sampling, mask-area ordering,
unassigned-point clustering and colour normalization. Only sampled pixels need
mask membership or world coordinates; the learned model is unchanged.
"""

import numpy as np


class Preprocessor:
    def __init__(self, config, checkpoint):
        from fastsam import FastSAM

        self.masks = FastSAM(checkpoint)
        self.mean = np.asarray(config["color_mean"])
        self.std = np.asarray(config["color_std"])

    def process_single_frame(self, color, depth_mm, pose, intrinsic):
        import torch
        from sklearn.cluster import KMeans

        valid = np.flatnonzero(depth_mm.ravel() > 0.1)
        if not len(valid):
            raise ValueError("No valid ESAM depth samples")
        prediction = self.masks(
            np.ascontiguousarray(color[:, :, ::-1]),
            device="cuda",
            retina_masks=True,
            imgsz=640,
            conf=0.1,
            iou=0.9,
        )[0]
        if prediction.masks is None:
            prediction = self.masks(
                np.ascontiguousarray(color[:, :, ::-1]),
                device="cuda",
                retina_masks=True,
                imgsz=640,
                conf=0.1,
                iou=0.7,
            )[0]
        indices = valid[np.random.choice(len(valid), 20000, replace=len(valid) < 20000)]
        y, x = np.divmod(indices, depth_mm.shape[1])
        groups = np.full(20000, -1, dtype=np.int64)
        if prediction.masks is not None:
            masks = prediction.masks.data == 1
            areas = masks.sum(dim=(1, 2)).cpu().numpy()
            order = np.argsort(-areas, kind="stable")
            selected = (
                masks[
                    :,
                    torch.as_tensor(y, device=masks.device),
                    torch.as_tensor(x, device=masks.device),
                ]
                .cpu()
                .numpy()
            )
            for group, index in enumerate(order):
                groups[selected[index]] = group
        rays = np.linalg.inv(intrinsic) @ np.stack((x, y, np.ones_like(x)))
        camera = rays * (depth_mm[y, x] / 1000)[None]
        homogeneous = pose @ np.vstack((camera, np.ones(20000)))
        xyz = (homogeneous[:3] / homogeneous[3:4]).T
        points = np.concatenate((xyz, color[y, x]), axis=1)
        unassigned = groups == -1
        if unassigned.sum() < 20:
            groups[unassigned] = groups.max() + 1
        else:
            groups[unassigned] = (
                KMeans(n_clusters=20, n_init=10).fit(points[unassigned]).labels_ + groups.max() + 1
            )
        _, groups = np.unique(groups, return_inverse=True)
        points[:, 3:] = (points[:, 3:] - self.mean) / self.std
        return groups, points
