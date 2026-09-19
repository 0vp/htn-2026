import asyncio
import importlib
import json


def test_codex_off_never_runs_agent(monkeypatch):
    bridge = importlib.import_module("htn_backend.voice.bridge")
    sent = []

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def __aiter__(self):
            async def events():
                for event in [
                    {"type": "session.input_transcript.delta", "delta": "Move to the table"},
                    {"type": "session.delegation.created", "delegation": {"id": "d1"}},
                    {"type": "session.delegation.created", "delegation": {"id": "d1"}},
                    {"type": "session.closed"},
                ]:
                    yield json.dumps(event)

            return events()

        async def send(self, value):
            sent.append(json.loads(value))

    async def forbidden(*args, **kwargs):
        raise AssertionError("Codex must not be called in conversation-only mode")

    monkeypatch.setattr(bridge, "connect", lambda *args, **kwargs: Socket())
    monkeypatch.setattr(bridge, "run", forbidden)
    asyncio.run(bridge.bridge("live_test", "not-a-key", "ABCDEF12", False, asyncio.Event()))
    assert len(sent) == 1
    assert sent[0]["delegation_id"] == "d1"
    assert "disconnected" in sent[0]["content"]
