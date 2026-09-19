"""Unknown and occluded object poses must not leak through the room tools."""

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mujoco")

from htn_backend.simulation.service import ROOM, create_app


def test_initial_occlusion_no_oracle_pose_or_evidence_and_manipulation_scope():
    with TestClient(create_app()) as client:
        prefix = f"/v1/rooms/{ROOM}"
        scene = client.get(prefix + "/scene").json()
        assert all(o["kind"] == "navigation_waypoint" for o in scene["objects"])
        assert "blue_block" not in str(scene)
        assert client.get(prefix + "/scene/search?q=blue").json()["objects"] == []
        assert client.get(prefix + "/objects/blue_block/evidence.jpg").status_code == 404
        request = dict(
            request_id="hidden",
            skill="navigate",
            object_id="blue_block",
            scene_revision=scene["revision"],
        )
        assert client.post(prefix + "/actions", json=request).status_code == 404
        assert scene["capabilities"]["pick"] and scene["capabilities"]["place"]
        assert "simulated rigid block" in scene["capabilities"]["manipulation_scope"]
        assert (
            client.post(
                prefix + "/actions",
                json={
                    **request,
                    "request_id": "unvalidated",
                    "skill": "pick",
                    "object_id": "viewpoint_1",
                },
            ).status_code
            == 422
        )
        observation = client.get(prefix + "/observations/latest").json()
        assert observation["view"] == "body-mounted robot POV"
        assert len(observation["camera"]["camera_to_room"]) == 4


def test_observation_changes_after_physical_navigation_and_remembers_only_seen_objects():
    with TestClient(create_app()) as client:
        sim = client.app.state.sim
        before = sim.view()[1]
        assert sim.executor.submit(sim.controller.execute, "navigate", "viewpoint_1").result(30)[0]
        sim.executor.submit(sim.publish, True).result(10)
        assert before != sim.view()[1]
        scene = sim.scene()
        table = next(o for o in scene["objects"] if o["object_id"] == "source_table")
        assert table["visibility"] == "last_seen" and table["visible_pixels"] >= 12
        assert table["age_simulation_s"] > 0
        saved = sim.evidence["source_table"]
        center = table["center"]
        sim.executor.submit(sim.publish, True).result(10)
        table_after = next(o for o in sim.scene()["objects"] if o["object_id"] == "source_table")
        assert table_after["center"] == center
        assert sim.evidence["source_table"] == saved
        assert saved != sim.view()[1]
