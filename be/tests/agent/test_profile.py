"""Inspect actual Codex model requests against a local, credential-free provider."""

import asyncio
import json
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from htn_backend.agent.profile import BASE_INSTRUCTIONS, MODEL, server_command, thread_params
from htn_backend.agent.protocol import AppServer
from htn_backend.agent.run import run_turn
from htn_backend.agent.tools import definitions


def test_profile_disables_inherited_mcp_without_copying_secrets(tmp_path):
    inherited = {"mcp_servers": {"work.docs": {"http_headers": {"key": "secret"}}}}
    params = thread_params(tmp_path, definitions(), inherited)
    assert params["config"]["mcp_servers"] == {"work.docs": {"enabled": False}}
    assert "secret" not in json.dumps(params)
    assert inherited["mcp_servers"]["work.docs"]["http_headers"]["key"] == "secret"


@pytest.mark.skipif(not shutil.which("codex"), reason="Official Codex CLI not installed")
def test_official_runtime_prompt_and_tool_surface(tmp_path):
    requests = []
    calls = []

    class RoomTools:
        def call(self, name, arguments):
            calls.append((name, arguments))
            return {
                "success": True,
                "contentItems": [
                    {"type": "inputText", "text": "scene-contract-ok"},
                ],
            }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(json.loads(body))
            events = [
                {"type": "response.created", "response": {"id": "test-response"}},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "test-response",
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                        },
                    },
                },
            ]
            if len(requests) == 1:
                events.insert(
                    1,
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "custom_tool_call",
                            "call_id": "room-check",
                            "namespace": "functions",
                            "name": "exec",
                            "input": (
                                "if (typeof tools.exec_command !== 'undefined' || "
                                "typeof tools.apply_patch !== 'undefined') "
                                "throw new Error('Unexpected coding capability');"
                                "text(await tools.read_scene({}));"
                            ),
                        },
                    },
                )
            payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()

    async def exercise():
        server = AppServer(server_command(shutil.which("codex")), RoomTools())
        try:
            await server.start()
            inherited = await server.request(
                "config/read", {"cwd": str(tmp_path), "includeLayers": False}
            )
            params = thread_params(tmp_path, definitions(), inherited["config"])
            params["config"].update(
                {
                    "model_provider": "robot-test",
                    "model_providers": {
                        "robot-test": {
                            "name": "Local robot contract test",
                            "base_url": f"http://127.0.0.1:{http.server_port}/v1",
                            "wire_api": "responses",
                            "requires_openai_auth": False,
                            "supports_websockets": False,
                        }
                    },
                    "features.enable_request_compression": False,
                }
            )
            params["modelProvider"] = "robot-test"
            result = await server.request("thread/start", params)
            assert result["model"] == MODEL
            await run_turn(server, result["thread"]["id"], "Read this room", emit=lambda _: None)
        finally:
            await server.close()

    try:
        asyncio.run(exercise())
    finally:
        http.shutdown()
        http.server_close()
        worker.join()

    assert requests, "Codex must send an actual model request to the test provider"
    assert calls == [("read_scene", {})], "The real tool host must execute the room tool"
    assert "scene-contract-ok" in json.dumps(requests[-1])
    request = requests[0]
    messages = [
        content.get("text", "") for item in request["input"] for content in item.get("content", [])
    ]
    assert BASE_INSTRUCTIONS in messages or request.get("instructions") == BASE_INSTRUCTIONS
    context = "\n".join(messages)
    assert "SKILL.md" not in context
    assert "multi_agent_role" not in context
    assert "You are a coding agent" not in context

    specs = request.get("tools", []) + [
        tool
        for item in request["input"]
        if item.get("type") == "additional_tools"
        for tool in item["tools"]
    ]
    leaves = [leaf for spec in specs for leaf in spec.get("tools", [spec])]
    names = {tool.get("name", tool["type"]) for tool in leaves}
    expected = {tool["name"] for tool in definitions()}
    if "exec" in names:  # Astra's model catalog selects Codex's tool-call wrapper.
        description = next(tool["description"] for tool in leaves if tool["name"] == "exec")
        nested = set(re.findall(r"^### `([^`]+)`", description, re.MULTILINE))
        assert nested == expected | {"clock__curr_time"}
        assert "bbox: Array<number>" in description
        assert names == {"exec", "wait", "request_user_input_async"}
    else:
        assert expected <= names <= expected | {"clock", "curr_time", "request_user_input_async"}
