"""Confirm native objects with independent image masks and measured surface depth."""

import numpy as np

from ...registration.rigid import difference
from .evidence import crop


class ObjectConfirmation:
    def __init__(self):
        self.tracks = {}
        self.timestamp_s = 0.0

    def update(self, frame, detections, objects, surfaces):
        active = {obj["object_id"] for obj in objects}
        self.tracks = {key: state for key, state in self.tracks.items() if key in active}
        h = frame.header
        self.timestamp_s = max(self.timestamp_s, h.timestamp_s)
        pose = np.array(h.camera_to_world).reshape(4, 4, order="F")
        masks = {}
        for detection in detections:
            if detection["score"] >= 0.5:
                label = detection["label"]
                masks.setdefault(label, []).append(detection)
        confirmed = []
        for obj in objects:
            key = obj["object_id"]
            state = self.tracks.setdefault(
                key,
                dict(
                    views=0,
                    pose=None,
                    score=None,
                    samples=0,
                    first=None,
                    last=-1.0,
                    confirmed=False,
                    devices=set(),
                    evidence=None,
                ),
            )
            points = np.asarray(surfaces.get(key, []))
            if len(points):
                camera = (points - pose[:3, 3]) @ pose[:3, :3]
                if h.camera_convention == "arkit":
                    camera *= [1, -1, -1]
                z = camera[:, 2]
                uv = np.rint(
                    camera[:, :2] / np.maximum(z[:, None], 1e-8) * [h.fx, h.fy] + [h.cx, h.cy]
                ).astype(int)
                inside = (
                    (z > 0.15)
                    & (z < 5)
                    & (uv[:, 0] >= 0)
                    & (uv[:, 0] < h.depth_width)
                    & (uv[:, 1] >= 0)
                    & (uv[:, 1] < h.depth_height)
                )
                uv, z = uv[inside], z[inside]
                _, unique = np.unique(uv, axis=0, return_index=True)
                uv, z = uv[unique], z[unique]
                x, y = uv.T
                visible = (frame.confidence[y, x] >= 2) & (
                    abs(frame.depth[y, x] - z) < 0.08 + 0.02 * z
                )
                candidates = masks.get(obj["label"], [])
                ratios = [
                    float(d["mask"][y[visible], x[visible]].mean()) if visible.sum() >= 6 else 0
                    for d in candidates
                ]
                best = int(np.argmax(ratios)) if ratios else None
                ratio = ratios[best] if best is not None else 0
                changed = state["pose"] is None or any(
                    v >= bound
                    for v, bound in zip(difference(pose, state["pose"]), (0.08, 8), strict=True)
                )
                if ratio >= 0.5 and changed:
                    state["views"] += 1
                    state["pose"] = pose.copy()
                    state["score"] = ratio
                if ratio >= 0.5 and h.timestamp_s - state["last"] >= 0.4:
                    if state["first"] is None:
                        state["first"] = h.timestamp_s
                    state["samples"] += 1
                    state["last"] = h.timestamp_s
                    state["score"] = ratio
                    device = (frame.provenance or {}).get("device_id")
                    if device:
                        state["devices"].add(device)
                    detection = candidates[best]
                    quality = float(detection["mask"].sum() * detection["score"])
                    if state["evidence"] is None or quality > state["evidence"]["quality"] * 1.2:
                        # Limit visual memory independently of native graph size.
                        cached = sum(s["evidence"] is not None for s in self.tracks.values())
                        if state["evidence"] is not None or cached < 128:
                            state["evidence"] = crop(frame, detection)
                state["confirmed"] |= state["views"] >= 2 or (
                    state["samples"] >= 3 and state["last"] - state["first"] >= 1.0
                )
            if state["confirmed"]:
                confirmed.append(self.decorate(obj, state))
        return confirmed

    def decorate(self, obj, state):
        obj.update(
            confirmed_views=state["views"],
            semantic_surface_support=state["score"],
            observations=state["samples"],
            source_devices=sorted(state["devices"]),
            last_confirmed_capture_s=state["last"],
            age_s=max(0.0, self.timestamp_s - state["last"]),
            evidence_digest=state["evidence"]["digest"] if state["evidence"] else None,
        )
        return obj

    def retained(self, objects):
        return [
            self.decorate(obj, self.tracks[obj["object_id"]])
            for obj in objects
            if self.tracks.get(obj["object_id"], {}).get("confirmed")
        ]
