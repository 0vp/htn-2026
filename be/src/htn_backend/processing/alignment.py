"""Verify capture origins against durable room-coordinate reference views."""

import json
from collections import OrderedDict
from dataclasses import replace

import numpy as np

from ..registration.hybrid import register
from ..registration.rigid import difference
from .atlas.references import References


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
        self.search_before = {}
        self.reference = []
        self.reference_ids = set()
        self.references = References(state.store, room_id)
        self.anchor = next((k for k, v in self.transforms.items() if v["status"] == "anchor"), None)
        for sequence, frame in self.references.frames():
            self.reference.append(features.extract(frame))
            self.reference_ids.add(sequence)

    def observe(self, row, frame) -> bool:
        stream = stream_key(row)
        if self.anchor is None:
            self.anchor = stream
            self.save(stream, {"status": "anchor", "room_from_local": np.eye(4).flatten().tolist()})
        transform = self.transform(row)
        if transform is not None:
            pose = transform @ np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
            if row["sequence"] in self.reference_ids:
                return False
            if self.reference and all(
                v < b
                for v, b in zip(difference(pose, self.reference[-1].pose), (0.12, 10), strict=True)
            ):
                return False
            world = replace(
                frame,
                header=frame.header.model_copy(
                    update={"camera_to_world": tuple(pose.flatten(order="F"))}
                ),
            )
            self.reference.append(self.features.extract(world))
            del self.reference[:-24]
            self.references.save(row["sequence"], world)
            # Identity bookkeeping stays bounded along with the persisted reference bank.
            self.reference_ids = self.references.ids()
            return False
        keys = self.keys.setdefault(stream, [])
        self.keys.move_to_end(stream)
        while len(self.keys) > 16:
            self.keys.popitem(last=False)
        pose = np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
        if keys and all(
            v < b for v, b in zip(difference(pose, keys[-1].pose), (0.12, 10), strict=True)
        ):
            return False
        keys.append(self.features.extract(frame))
        del keys[:-8]
        if len(keys) < 5 or len(self.reference) < 5:
            return False
        target = self.reference
        before = self.search_before.get(stream)
        bank = self.references.frames(before=before)
        if before is not None and len(bank) >= 5:
            target = [self.features.extract(f) for _, f in bank]
        self.features.prefetch([(a, b) for a in keys for b in target])
        result = register(keys, target, match=self.features)
        if result["status"] != "aligned":
            self.state.align(self.room_id, stream, result)
            self.search_before[stream] = min(n for n, _ in bank) if len(bank) >= 5 else None
            return False
        self.save(stream, result)
        self.keys.pop(stream, None)
        self.search_before.pop(stream, None)
        return True

    def save(self, stream, evidence):
        self.transforms[stream] = evidence
        self.state.align(self.room_id, stream, evidence)

    def transform(self, row):
        value = self.transforms.get(stream_key(row), {}).get("room_from_local")
        return None if value is None else np.array(value).reshape(4, 4, order="F")
