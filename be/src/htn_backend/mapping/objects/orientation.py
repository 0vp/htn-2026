"""Keep equivalent measured box axes stable; do not invent semantic facing direction."""

import numpy as np


class AxialOrientation:
    def __init__(self):
        self.previous = {}

    def update(self, objects):
        active = {o["object_id"] for o in objects}
        self.previous = {k: v for k, v in self.previous.items() if k in active}
        for obj in objects:
            key = obj["object_id"]
            yaw = float(obj["yaw_rad"])
            extent = list(obj["size_m"])
            previous = self.previous.get(key)
            candidates = []
            for turn in range(4):
                angle = yaw + turn * np.pi / 2
                size = extent if turn % 2 == 0 else [extent[2], extent[1], extent[0]]
                if previous is None:
                    cost = (0 if size[0] >= size[2] else 10) + (angle % np.pi)
                else:
                    angle = previous + np.arctan2(
                        np.sin(angle - previous), np.cos(angle - previous)
                    )
                    cost = abs(angle - previous)
                candidates.append((cost, angle, size))
            _, angle, size = min(candidates, key=lambda x: x[0])
            if previous is None:
                angle %= np.pi
            obj["yaw_rad"], obj["size_m"] = float(angle), size
            obj["orientation_status"] = "measured_box_axes; semantic_facing_unknown"
            obj["orientation_symmetry_rad"] = float(np.pi)
            self.previous[key] = angle
        return objects
