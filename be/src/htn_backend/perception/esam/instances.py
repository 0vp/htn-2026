"""Associate independent 3D instances; category labels never become identities."""

import numpy as np
from scipy.optimize import linear_sum_assignment

from ...mapping.bounds import fit_upright_bounds
from .calibration import visible_pixels


def voxels(points):
    cells = np.ascontiguousarray(np.floor(points / 0.06).astype(np.int32))
    return np.unique(cells.view(np.dtype((np.void, 12))).ravel())


class InstanceCatalog:
    """Bounded to an active mapping segment; the room atlas owns sealed instances."""

    def __init__(self):
        self.tracks = {}
        self.next_id = 0

    def update(self, frame, detections, result):
        points = np.asarray(result["points"], dtype=np.float32)
        offsets = np.asarray(result["offsets"])
        scores = np.asarray(result["scores"])
        if (
            points.ndim != 2
            or points.shape[1] != 3
            or not np.isfinite(points).all()
            or offsets.dtype.kind not in "iu"
            or offsets.ndim != 1
            or len(offsets) != len(scores) + 1
            or offsets[0] != 0
            or offsets[-1] != len(points)
            or np.any(np.diff(offsets) < 0)
            or scores.ndim != 1
            or not np.isfinite(scores).all()
            or np.any((scores < 0) | (scores > 1))
        ):
            raise ValueError("Invalid ESAM instance output")
        candidates = []
        for i, score in enumerate(scores):
            cloud = points[offsets[i] : offsets[i + 1]].copy()
            if score < 0.3 or len(cloud) < 20:
                continue
            y, x = visible_pixels(frame, cloud)
            votes = {}
            for d in detections:
                if np.asarray(d["mask"]).shape != frame.depth.shape:
                    raise ValueError("Detection mask does not match depth calibration")
                if len(x) >= 6 and np.isfinite(d["score"]) and d["score"] >= 0.5:
                    support = float(np.mean(d["mask"][y, x]))
                    if support >= 0.5:
                        votes[d["label"]] = max(
                            votes.get(d["label"], 0), support * float(d["score"])
                        )
            candidates.append(
                dict(
                    points=cloud,
                    voxels=voxels(cloud),
                    votes=votes,
                    score=score,
                    low=cloud.min(axis=0),
                    high=cloud.max(axis=0),
                )
            )
        keys = list(self.tracks)
        overlap = np.zeros((len(candidates), len(keys)))
        if candidates and keys:
            low = np.array([c["low"] for c in candidates])[:, None]
            high = np.array([c["high"] for c in candidates])[:, None]
            prior_low = np.array([self.tracks[key]["low"] for key in keys])[None]
            prior_high = np.array([self.tracks[key]["high"] for key in keys])[None]
            possible = ((low <= prior_high + 0.06) & (high >= prior_low - 0.06)).all(axis=2)
            for i, j in np.argwhere(possible):
                a, b = candidates[i]["voxels"], self.tracks[keys[j]]["voxels"]
                common = len(np.intersect1d(a, b, assume_unique=True))
                overlap[i, j] = common / max(1, len(a) + len(b) - common)
        matches = {}
        if overlap.size:
            rows, cols = linear_sum_assignment(-overlap)
            matches = {i: keys[j] for i, j in zip(rows, cols, strict=True) if overlap[i, j] >= 0.1}
        for i, candidate in enumerate(candidates):
            key = matches.get(i)
            if key is None:
                key = f"instance-{self.next_id}"
                self.next_id += 1
                self.tracks[key] = dict(votes={}, observations=0)
            track = self.tracks[key]
            # The upstream merger already fuses geometry within its active window.
            # Across windows this update uses measured surfaces, not invented extents.
            track.update({k: candidate[k] for k in ("points", "voxels", "score", "low", "high")})
            for label, vote in candidate["votes"].items():
                track["votes"][label] = track["votes"].get(label, 0.0) + vote
            track["observations"] += 1
        return self.snapshot()

    def snapshot(self):
        objects, surfaces = [], {}
        for key, track in self.tracks.items():
            if not track["votes"]:
                continue
            center, size, yaw = fit_upright_bounds(track["points"])
            surfaces[key] = track["points"]
            objects.append(
                dict(
                    object_id=key,
                    label=max(track["votes"], key=track["votes"].get),
                    score=float(track["score"]),
                    center_m=center.tolist(),
                    size_m=size.tolist(),
                    yaw_rad=yaw,
                    observations=track["observations"],
                    points=len(track["points"]),
                    state="mapped",
                    identity_status="esam_instance",
                    source_devices=[],
                    geometry_status="observed surface bounds; hidden shape unknown",
                    extent_kind="visible_surface_estimate",
                    representation="generic_category_model",
                )
            )
        return objects, surfaces
