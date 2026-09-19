"""Conservative temporal visibility; native Hydra remains the identity/geometry owner."""

from collections import deque

from .visibility import evidence


class ObjectLifecycle:
    def __init__(self):
        self.tracks = {}
        self.events = deque(maxlen=128)

    def update(self, frame, objects, surfaces):
        timestamp = frame.header.timestamp_s
        active = {obj["object_id"] for obj in objects}
        self.tracks = {key: value for key, value in self.tracks.items() if key in active}
        for obj in objects:
            key = obj["object_id"]
            state = self.tracks.setdefault(
                key, dict(free_views=0, last_free=-1.0, last_observed=None, absent=False)
            )
            measured = evidence(frame, surfaces.get(key, []))
            count = measured["visible"]
            if count >= 12 and measured["occupied"] / count >= 0.5:
                state.update(free_views=0, last_observed=timestamp, absent=False)
            elif count >= 12 and measured["free"] / count >= 0.8:
                if timestamp - state["last_free"] >= 0.2:
                    state["free_views"] += 1
                    state["last_free"] = timestamp
                if state["free_views"] >= 3 and not state["absent"]:
                    state["absent"] = True
                    self.events.append(
                        dict(
                            object_id=key,
                            event="location_vacated",
                            timestamp_s=timestamp,
                            evidence=measured,
                        )
                    )
            elif count >= 12 and measured["occupied"]:
                state["free_views"] = 0
            obj["visibility"] = (
                "absent"
                if state["absent"]
                else ("observed" if state["last_observed"] == timestamp else "unobserved")
            )
            obj["last_surface_observed_s"] = state["last_observed"]
            obj["free_space_observations"] = state["free_views"]
            if state["absent"]:
                obj["state"] = "location_vacated"
                obj["representation"] = "observed_bounds"
        return [obj for obj in objects if obj["visibility"] != "absent"]
