"""Camera -> retained RGB-D -> production grounding -> room surface, over HTTP."""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mujoco")

from htn_backend.agent.tools import RobotTools
from htn_backend.simulation.service import ROOM, create_app


def test_rendered_wall_grounding_matches_geometry_without_object_pose():
    with TestClient(create_app(layout="open")) as client:
        tools = RobotTools(client, ROOM)
        observation = json.loads(tools.call("observe", {})["contentItems"][0]["text"])
        assert observation["depth_available"]
        # Middle camera rays hit the room's east wall, whose inner face is x=3.1m.
        result = tools.call(
            "ground_region",
            dict(sequence=observation["sequence"], bbox=[0.45, 0.45, 0.55, 0.55], label="wall"),
        )
        assert result["success"]
        grounded = json.loads(result["contentItems"][0]["text"])
        assert abs(grounded["room_surface_center_m"][0] - 3.1) < 0.005
        assert grounded["supporting_depth_pixels"] > 100
        assert grounded["object_pose"] is None and not grounded["grasp_ready"]
        assert not grounded["semantic_verification"]
        assert grounded["requires_reobservation"]
        assert "not SLAM" in grounded["pose_source"]


def test_bad_missing_and_expired_depth_are_not_successful_grounding():
    with TestClient(create_app(layout="open")) as client:
        sim = client.app.state.sim
        path = f"/v1/rooms/{ROOM}/observations/ground"
        request = dict(sequence=1, bbox=[0.45, 0.45, 0.55, 0.55], label="wall")
        assert client.post(path, json={**request, "bbox": [1, 0, 0, 1]}).status_code == 422
        assert client.post(path, json={**request, "sequence": 999}).status_code == 410
        with sim.lock:
            sim.depth_frames[1].depth[:] = np.nan
        response = client.post(path, json=request)
        assert response.status_code == 409
        assert "Insufficient" in response.json()["detail"]
        for _ in range(33):
            sim.executor.submit(sim.publish, True).result(timeout=10)
        assert len(sim.depth_frames) == len(sim.views) == 32
        assert client.post(path, json=request).status_code == 410


def test_historical_grounding_keeps_capture_pose_and_reports_age():
    with TestClient(create_app(layout="open")) as client:
        sim = client.app.state.sim
        path = f"/v1/rooms/{ROOM}/observations/ground"
        request = dict(sequence=1, bbox=[0.45, 0.45, 0.55, 0.55], label="wall")
        before = client.post(path, json=request).json()
        sim.executor.submit(sim.world.step, 1.0).result(timeout=10)
        after = client.post(path, json=request).json()
        assert after["room_surface_center_m"] == before["room_surface_center_m"]
        assert after["capture_timestamp_s"] == before["capture_timestamp_s"]
        assert after["age_simulation_s"] >= 0.99
