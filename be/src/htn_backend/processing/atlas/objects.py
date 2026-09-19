"""Stable object identities across native segment lifetimes."""

import copy

import numpy as np


def combine(previous: list[dict], current: list[dict], evidence: dict, generation: int):
    objects = {o["object_id"]: copy.deepcopy(o) for o in previous}
    images = {}
    assigned = set()
    for item in current:
        obj = copy.deepcopy(item)
        candidates = []
        for key, old in objects.items():
            if key in assigned or old["label"] != obj["label"]:
                continue
            delta = np.linalg.norm(np.array(old["center_m"]) - obj["center_m"])
            a, b = np.array(old["size_m"]), np.array(obj["size_m"])
            # A nearby, similarly sized observation can refresh an existing region.
            if delta < 0.20 and np.max(np.maximum(a, b) / np.maximum(np.minimum(a, b), 0.015)) < 2:
                candidates.append((delta, key))
        key = min(candidates)[1] if candidates else f"{generation}:{obj['object_id']}"
        source = obj["object_id"]
        obj["object_id"] = key
        objects[key] = obj
        assigned.add(key)
        if source in evidence:
            images[key] = evidence[source]
    return list(objects.values()), images
