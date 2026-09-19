"""Candidate mapper: Hydra geometry with independently segmented ESAM objects."""

from ...mapping.hydra.client import HydraClient
from ...mapping.loops.poses import corrected_frame
from .client import EsamClient
from .instances import InstanceCatalog


class HydraEsam:
    """Implements RoomProcessor's mapper contract without a user-selectable profile."""

    def __init__(self, geometry_factory=HydraClient, instance_factory=EsamClient):
        self.geometry = geometry_factory()
        self.instances = instance_factory()
        self.history = []
        self.objects, self.surfaces, self.timing = [], {}, {}
        self.revisions = 0

    def integrate(self, frame, detections, loops=()):
        if len(self.history) >= 256:
            raise RuntimeError("Seal the active mapping segment before adding more frames")
        result = self.geometry.integrate(frame, detections, loops)
        self.history.append((frame, detections))
        if loops:
            if not result.get("updated", True):
                result = self.geometry.flush()
            self.rebuild(result)
        else:
            self.objects, self.surfaces, self.timing = self.instances.integrate(frame, detections)
        return self.attach(result)

    def flush(self, loops=()):
        result = self.geometry.flush(loops)
        if loops:
            self.rebuild(result)
        return self.attach(result) if result is not None else None

    def rebuild(self, result):
        # Mixing corrected geometry with stale instance points is unsafe. Replay the
        # bounded active segment with exact optimized poses before publishing either.
        frames = [corrected_frame(frame, result.get("agents", [])) for frame, _ in self.history]
        if any(frame is None for frame in frames):
            raise RuntimeError("ESAM replay requires an optimized pose for every active frame")
        self.revisions += 1
        self.instances.catalog = InstanceCatalog()
        for i, (frame, (_, detections)) in enumerate(zip(frames, self.history, strict=True)):
            self.objects, self.surfaces, self.timing = self.instances.integrate(
                frame, detections, reset_window=i == 0
            )
        self.history = [
            (frame, detections) for frame, (_, detections) in zip(frames, self.history, strict=True)
        ]

    def attach(self, result):
        if result is None:
            raise RuntimeError("Hydra did not return geometry")
        prefix = f"esam-{self.revisions}-"
        objects = [dict(obj, object_id=prefix + obj["object_id"]) for obj in self.objects]
        return dict(
            result,
            instance_objects=objects,
            instance_surfaces={prefix + key: points for key, points in self.surfaces.items()},
            instance_timing=self.timing,
        )

    def close(self):
        try:
            self.geometry.close()
        finally:
            self.instances.close()
