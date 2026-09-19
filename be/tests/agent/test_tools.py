"""Verify tools against the actual HTTP app, including model-generated bad arguments."""

import json

from conftest import packet, room, upload

from htn_backend.agent.tools import RobotTools, definitions


def test_tools_read_actual_camera_and_keep_room_scoped(client):
    code = room(client)
    upload(client, code, packet())
    tools = RobotTools(client, code)
    result = tools.call("observe", {})
    assert result["success"]
    assert result["contentItems"][1]["imageUrl"].startswith("data:image/jpeg;base64,")
    scene = tools.call("read_scene", {})
    assert not json.loads(scene["contentItems"][0]["text"])["capabilities"]["pick"]
    assert not tools.call("read_scene", {"room_id": "OTHER"})["success"]
    assert not tools.call("unknown", {})["success"]
    assert not tools.call("request_skill", {"skill": "shell", "command": "anything"})["success"]
    assert {d["name"] for d in definitions()} >= {"observe", "request_skill"}


def test_tools_return_errors_without_faking_action_success(client):
    code = room(client)
    tools = RobotTools(client, code)
    assert not tools.call("observe", {})["success"]
    result = tools.call(
        "request_skill", {"request_id": "stop-1", "skill": "stop", "scene_revision": 0}
    )
    receipt = json.loads(result["contentItems"][0]["text"])
    assert result["success"]  # HTTP tool call succeeded, physical action did not.
    assert receipt["state"] == "blocked" and not receipt["physical_success"]
