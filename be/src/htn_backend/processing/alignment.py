"""Keep capture origins separate until independent RGB-D views agree."""

import json
from collections import OrderedDict

import numpy as np

from ..registration.hybrid import register
from ..registration.rigid import difference


def stream_key(row: dict) -> str:
    h = row["header"]
    return json.dumps([row["device_id"], h["session_id"], h["epoch"]], separators=(",", ":"))


class Alignment:
    def __init__(self, state, room_id, features):
        self.state, self.room_id, self.features = state, room_id, features
        self.transforms = {
            k: v for k, v in state.transforms(room_id).items() if "room_from_local" in v
        }
        self.keys = OrderedDict()
        self.anchor = next((k for k, v in self.transforms.items() if v["status"] == "anchor"), None)

    def observe(self, row, frame) -> bool:
        stream = stream_key(row)
        if self.anchor is None:
            self.anchor = stream
            self.save(stream, {"status": "anchor", "room_from_local": np.eye(4).flatten().tolist()})
        # Only the anchor and currently unresolved stream consume keyframe memory.
        if stream != self.anchor and stream in self.transforms:
            return False
        keys = self.keys.setdefault(stream, [])
        self.keys.move_to_end(stream)
        if len(self.keys) > 17:
            raise ValueError("Too many concurrent capture origins; close this room")
        pose = np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
        if keys and all(
            v < b for v, b in zip(difference(pose, keys[-1].pose), (0.12, 10), strict=True)
        ):
            return False
        key = self.features.extract(frame)
        keys.append(key)
        del keys[: -(24 if stream == self.anchor else 8)]
        if stream == self.anchor or len(keys) < 5 or len(self.keys.get(self.anchor, [])) < 5:
            return False
        target = self.keys[self.anchor]
        self.features.prefetch([(a, b) for a in keys for b in target])
        result = register(keys, target, match=self.features)
        if result["status"] != "aligned":
            # Persist refusal evidence without pretending a coordinate transform exists.
            self.state.align(self.room_id, stream, result)
            return False
        self.save(stream, result)
        return True

    def save(self, stream, evidence):
        self.transforms[stream] = evidence
        self.state.align(self.room_id, stream, evidence)

    def transform(self, row):
        result = self.transforms.get(stream_key(row), {})
        value = result.get("room_from_local")
        return None if value is None else np.array(value).reshape(4, 4, order="F")
