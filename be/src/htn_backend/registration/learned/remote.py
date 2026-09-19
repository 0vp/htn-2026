"""GPU appearance client; all metric coordinates come from the original measured frame."""

import hashlib
import struct
from dataclasses import dataclass

import httpx
import numpy as np

from ...capture.frame import Frame
from ...mapping.projection import project
from ..features import Keyframe
from ..optimization.matches import PairMatches
from .projection import lift


@dataclass(frozen=True)
class LearnedKeyframe(Keyframe):
    token: str
    payload: bytes
    frame: Frame


class RemoteFeatures:
    def __init__(self, endpoint: str, token: str):
        self.client = httpx.Client(
            base_url=endpoint.rstrip("/"), timeout=5, headers={"Authorization": f"Bearer {token}"}
        )
        self.matches = PairMatches(match=self._match)

    def clear(self):
        self.matches.clear()

    def close(self):
        self.client.close()

    def extract(self, frame: Frame) -> LearnedKeyframe:
        header = frame.header.model_dump_json().encode()
        payload = b"R3I1" + struct.pack("<I", len(header)) + header + frame.rgb_jpeg
        if len(payload) > 2_000_000:
            raise ValueError("feature image exceeds RPC limit")
        token = hashlib.sha256(payload).hexdigest()
        response = self.client.post("/features", content=payload)
        response.raise_for_status()
        result = response.json()
        if result.get("id") != token or result.get("model") != "xfeat-1600":
            raise ValueError("feature response identity mismatch")
        points = lift(frame, result["keypoints"])
        valid = (frame.confidence >= 2) & np.isfinite(frame.depth)
        valid &= (frame.depth > 0.15) & (frame.depth < 5)
        cloud = project(frame, stride=5, mask=valid)
        pose = np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
        return LearnedKeyframe(
            frame.header.frame_id,
            pose,
            points,
            np.empty((0, 32), np.uint8),
            cloud,
            token,
            payload,
            frame,
        )

    def _match(self, source: LearnedKeyframe, target: LearnedKeyframe):
        return self._match_many([(source, target)])[0]

    def prefetch(self, pairs):
        self.matches.prime(pairs, self._match_many)

    def _match_many(self, pairs):
        results = []
        for offset in range(0, len(pairs), 8):
            group = pairs[offset : offset + 8]
            payload = self._request_matches(group)
            if not isinstance(payload, list) or len(payload) != len(group):
                raise ValueError("invalid match batch response")
            results.extend(
                self._lift(source, target, result)
                for (source, target), result in zip(group, payload, strict=True)
            )
        return results

    def _request_matches(self, pairs):
        for attempt in range(2):
            response = self.client.post(
                "/match", json={"pairs": [[source.token, target.token] for source, target in pairs]}
            )
            if response.status_code != 409 or attempt:
                break
            # A GPU restart or bounded LRU eviction needs fresh descriptors, never a room reset.
            keyframes = {key.token: key for pair in pairs for key in pair}
            for keyframe in keyframes.values():
                restored = self.client.post("/features", content=keyframe.payload)
                restored.raise_for_status()
        response.raise_for_status()
        if len(response.content) > 4_000_000:
            raise ValueError("feature match response too large")
        return response.json()

    @staticmethod
    def _lift(source, target, result):
        a = lift(source.frame, result["keypoints0"])
        b = lift(target.frame, result["keypoints1"])
        scores = np.asarray(result["scores"], dtype=float)
        if len(a) != len(b) or scores.shape != (len(a),) or not np.isfinite(scores).all():
            raise ValueError("invalid learned correspondences")
        valid = np.isfinite(a).all(1) & np.isfinite(b).all(1)
        selected = np.flatnonzero(valid)
        selected = selected[np.argsort(-scores[selected], kind="stable")[:250]]
        return a[selected], b[selected]

    def __call__(self, source, target):
        return self.matches(source, target)
