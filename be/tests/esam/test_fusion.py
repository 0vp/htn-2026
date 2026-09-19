"""Geometry and instance publication must stay in the same optimized coordinate frame."""

import numpy as np
import pytest

from htn_backend.perception.esam.fusion import HydraEsam

from .test_instances import scene


class Geometry:
    def __init__(self):
        self.result = {"updated": True, "vertices": np.zeros((0, 3))}
        self.closed = False

    def integrate(self, frame, detections, loops=()):
        return self.result

    def flush(self, loops=()):
        return self.result

    def close(self):
        self.closed = True


class Instances:
    def __init__(self):
        self.calls = []
        self.closed = False

    def integrate(self, frame, detections, reset_window=False):
        self.calls.append((frame, reset_window))
        return [dict(object_id="instance-0", label="table")], {"instance-0": [[0, 0, 0]]}, {}

    def close(self):
        self.closed = True


def test_attaches_instances_without_changing_geometry():
    frame, detections, _ = scene()
    mapper = HydraEsam(Geometry, Instances)
    result = mapper.integrate(frame, detections)
    assert result["vertices"] is mapper.geometry.result["vertices"]
    assert result["instance_objects"][0]["object_id"] == "esam-0-instance-0"
    assert mapper.flush()["instance_surfaces"] == {"esam-0-instance-0": [[0, 0, 0]]}
    mapper.close()
    assert mapper.geometry.closed and mapper.instances.closed


def test_loop_closure_requires_complete_optimized_poses():
    frame, detections, _ = scene()
    mapper = HydraEsam(Geometry, Instances)
    mapper.integrate(frame, detections)
    with pytest.raises(RuntimeError, match="optimized pose for every"):
        mapper.flush(loops=["loop"])
    assert len(mapper.instances.calls) == 1


def test_loop_replays_instances_at_corrected_metric_pose():
    frame, detections, _ = scene()
    mapper = HydraEsam(Geometry, Instances)
    mapper.integrate(frame, detections)
    # Native agent translation is Z-up. A +2 X correction stays +2 X in room space.
    mapper.geometry.result["agents"] = np.array([[1, 2, 0, 0, 1, 0, 0, 0]])
    result = mapper.flush(loops=["loop"])
    corrected, reset = mapper.instances.calls[-1]
    assert reset
    assert corrected.header.camera_to_world[12] == 2
    assert result["instance_objects"][0]["object_id"] == "esam-1-instance-0"
