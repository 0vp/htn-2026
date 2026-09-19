import asyncio
import importlib
import json

import httpx

module = importlib.import_module("htn_backend.agent.feedback.stream")


def test_phase_changes_are_coalesced_and_bound_to_active_turn(monkeypatch):
    phases = iter(["idle", "navigate", "navigate", "pregrasp", "completed"])
    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            phase = next(phases, "completed")
            return httpx.Response(
                200,
                json=dict(
                    execution_domain="simulation",
                    action_id=None if phase == "idle" else "action",
                    phase=phase,
                ),
                request=httpx.Request("GET", "http://localhost" + url),
            )

    class Server:
        async def request(self, method, params):
            calls.append((method, params))
            if len(calls) == 3:
                raise RuntimeError("turn already completed")

    original_sleep = asyncio.sleep
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: Client())
    monkeypatch.setattr(module.asyncio, "sleep", lambda _: original_sleep(0.001))
    asyncio.run(module.stream(Server(), "thread", "turn", "http://localhost", "/room"))
    assert len(calls) == 3
    for method, params in calls:
        assert method == "turn/steer" and params["expectedTurnId"] == "turn"
        assert params["threadId"] == "thread"
        text = params["input"][0]["text"]
        assert "untrusted data" in text
        assert json.loads(text.split("\n", 1)[1])["action_id"] == "action"


def test_reported_hardware_telemetry_does_not_become_an_authenticated_event(monkeypatch):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return httpx.Response(
                200,
                json=dict(execution_domain="hardware_telemetry"),
                request=httpx.Request("GET", "http://localhost" + url),
            )

    class Server:
        async def request(self, *args):
            raise AssertionError("must not steer")

    original_sleep = asyncio.sleep
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: Client())
    monkeypatch.setattr(module.asyncio, "sleep", lambda _: original_sleep(0.001))
    asyncio.run(module.stream(Server(), "thread", "turn", "http://localhost", "/room"))
