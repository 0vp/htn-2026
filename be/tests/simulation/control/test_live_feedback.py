import json
import time

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mujoco")

from htn_backend.agent.tools import RobotTools
from htn_backend.simulation.service import ROOM, create_app


def test_feedback_advances_during_action_and_receipt_contains_measured_state():
    with TestClient(create_app(layout="open")) as client:
        tools = RobotTools(client, ROOM)
        before = json.loads(tools.call("read_feedback", {})["contentItems"][0]["text"])
        prefix = f"/v1/rooms/{ROOM}"
        action = client.post(
            prefix + "/actions",
            json=dict(
                request_id="feedback", skill="navigate", object_id="blue_block", scene_revision=1
            ),
        ).json()
        deadline = time.monotonic() + 20
        observed_running = False
        while time.monotonic() < deadline:
            receipt = client.get(prefix + "/actions/" + action["action_id"]).json()
            feedback = receipt["live_feedback"]
            if feedback["sequence"] > before["sequence"]:
                assert set(feedback["joints"]) >= {
                    "wheel",
                    "steering",
                    "shoulder",
                    "elbow",
                    "wrist",
                }
                assert feedback["source"].startswith("MuJoCo measured")
                assert "object_position" not in feedback
                observed_running |= receipt["state"] == "running"
            if receipt["state"] != "running":
                break
            time.sleep(0.02)
        assert observed_running and receipt["simulation_success"]
        assert not receipt["physical_success"]
        after = client.get(prefix + "/robot/feedback").json()
        assert after["action_id"] == action["action_id"]
        assert after["phase"] == "completed"
