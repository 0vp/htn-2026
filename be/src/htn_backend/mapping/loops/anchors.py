"""Express visual constraints at actual native keyframes, never nearest unadjusted poses."""

from collections import OrderedDict, deque

import numpy as np

from ...registration.rigid import difference


class NativeAnchors:
    def __init__(self):
        self.poses = OrderedDict()
        self.stamps = []
        self.pending = deque(maxlen=8)

    def observe(self, frame):
        stamp = round(frame.header.timestamp_s * 1e6)
        pose = np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
        self.poses[stamp] = pose
        while len(self.poses) > 1800:
            self.poses.popitem(last=False)

    def update(self, agents):
        self.stamps = sorted({round(row[0] * 1e6) for row in agents} & self.poses.keys())

    def resolve(self, edges):
        self.pending.extend(edges)
        if not self.stamps:
            return []
        ready, waiting = [], deque(maxlen=8)
        for edge in self.pending:
            source = round(edge["from_timestamp_ns"] / 1000)
            target = round(edge["to_timestamp_ns"] / 1000)
            if source not in self.poses or target not in self.poses:
                continue
            endpoints, valid = [], True
            for stamp, support_name in [(source, "verified_from_ns"), (target, "verified_to_ns")]:
                support = {round(value / 1000) for value in edge.get(support_name, [])}
                available = support.intersection(self.stamps)
                anchor = min(available or self.stamps, key=lambda value: abs(value - stamp))
                endpoints.append(anchor)
                # Prefer an actual native node inside the geometrically verified
                # view set. Outside it, allow only a short, small odometry bridge.
                if not available:
                    distance, angle = difference(self.poses[anchor], self.poses[stamp])
                    valid &= abs(anchor - stamp) <= 500_000 and distance <= 0.25 and angle <= 15
            a, b = endpoints
            if not valid or a <= b:
                if source > self.stamps[-1]:
                    waiting.append(edge)
                continue
            # Adjust both endpoints using their ORIGINAL poses. Optimized poses
            # would apply previous graph corrections twice.
            relative = (
                np.linalg.inv(self.poses[b])
                @ self.poses[target]
                @ np.asarray(edge["to_T_from"])
                @ np.linalg.inv(self.poses[source])
                @ self.poses[a]
            )
            ready.append(
                dict(
                    from_timestamp_ns=a * 1000,
                    to_timestamp_ns=b * 1000,
                    to_T_from=relative.tolist(),
                )
            )
        self.pending = waiting
        return ready
