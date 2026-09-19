"""Exercise the real room tools over HTTP against isolated simulation physics."""

import json
import time

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mujoco")

from htn_backend.agent.tools import RobotTools
from htn_backend.simulation.service import ROOM, create_app


def completed(client, ident):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        receipt = client.get(f"/v1/rooms/{ROOM}/actions/{ident}").json()
        if receipt["state"] != "running":
            return receipt
        time.sleep(0.01)
    pytest.fail("Simulation action did not terminate")


def test_same_agent_tools_and_idempotency_without_physical_success():
    with TestClient(create_app()) as client:
        tools = RobotTools(client, ROOM)
        scene = json.loads(tools.call("read_scene", {})["contentItems"][0]["text"])
        assert scene["execution_domain"] == "simulation"
        assert tools.call("observe", {})["contentItems"][1]["type"] == "inputImage"
        request = dict(
            request_id="navigate",
            skill="navigate",
            object_id="viewpoint_1",
            scene_revision=scene["revision"],
        )
        result = tools.call("request_skill", request)
        receipt = json.loads(result["contentItems"][0]["text"])
        path = f"/v1/rooms/{ROOM}/actions"
        assert client.post(path, json=request).json()["action_id"] == receipt["action_id"]
        assert client.post(path, json={**request, "object_id": "delivery_table"}).status_code == 409
        final = completed(client, receipt["action_id"])
        assert final["simulation_success"] is True
        assert final["physical_success"] is False
        assert "object_position" not in final["result"]
        assert len(client.app.state.sim.receipts) == 1
        assert client.post(path, json={**request, "request_id": "stale"}).status_code == 409
        assert client.get("/v1/rooms/AAAAAAAA/scene").status_code == 404
        assert client.post(f"/v1/rooms/{ROOM}/observations/ground", json={}).status_code == 422


def test_stop_cancels_running_action_and_has_measured_simulated_receipt():
    with TestClient(create_app()) as client:
        path = f"/v1/rooms/{ROOM}/actions"
        move = client.post(
            path,
            json=dict(
                request_id="move", skill="navigate", object_id="viewpoint_1", scene_revision=1
            ),
        ).json()
        stop = client.post(
            path, json=dict(request_id="stop", skill="stop", scene_revision=0)
        ).json()
        final_stop = completed(client, stop["action_id"])
        final_move = completed(client, move["action_id"])
        assert final_move["state"] == "cancelled"
        assert not final_move["simulation_success"]
        assert final_stop["state"] == "completed" and final_stop["simulation_success"]
        assert not final_stop["physical_success"]
        assert client.app.state.sim.active is None
