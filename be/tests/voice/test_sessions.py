import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from htn_backend.main import create_app
from htn_backend.voice import service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-key")
    monkeypatch.setattr(service, "codex_binary", lambda: None)

    async def bridge(ident, key, room, enabled, ready):
        ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "bridge", bridge)
    app = create_app(tmp_path)
    requests = []

    def upstream(request):
        requests.append(request)
        if request.url.path.endswith("/hangup"):
            return httpx.Response(200, json={})
        return httpx.Response(
            201, json={"session": {"id": "live_test"}, "transport": {"sdp": "answer"}}
        )

    app.state.voice.client = httpx.AsyncClient(
        base_url="https://api.openai.com/v1", transport=httpx.MockTransport(upstream)
    )
    with TestClient(app) as client:
        room = client.post("/v1/rooms", json={"name": "Voice", "device_id": "leader"}).json()
        yield client, room["room_id"], requests


def offer(codex=False, request="one"):
    return {
        "device_id": "leader",
        "sdp": "v=0 fake offer",
        "codex_enabled": codex,
        "request_id": request,
    }


def test_conversation_mode_isolated_and_idempotent(client):
    import json

    client, room, requests = client
    path = f"/v1/rooms/{room}/voice"
    assert client.get(path + "/capabilities", params={"device_id": "leader"}).json() == {
        "available": True,
        "codex_available": False,
    }
    result = client.post(path + "/sessions", json=offer())
    assert result.status_code == 201
    assert result.json()["codex_enabled"] is False
    assert "test-not-a-key" not in result.text
    assert client.post(path + "/sessions", json=offer()).json() == result.json()
    assert len(requests) == 1
    config = json.loads(requests[0].content)["session"]
    assert config["model"] == "gpt-live-1"
    assert "Codex is disconnected" in config["instructions"]
    assert client.post(path + "/sessions", json=offer(request="two")).status_code == 409
    client.post(f"/v1/rooms/{room}/close")
    assert client.post(
        path + "/end", json={"device_id": "leader", "session_id": "live_test"}
    ).json() == {"ended": True}
    assert requests[-1].url.path.endswith("/hangup")


def test_unavailable_codex_never_silently_changes_mode(client):
    client, room, requests = client
    result = client.post(f"/v1/rooms/{room}/voice/sessions", json=offer(codex=True))
    assert result.status_code == 503
    assert not requests


def test_only_leader_and_no_client_config_injection(client):
    client, room, requests = client
    path = f"/v1/rooms/{room}/voice"
    assert (
        client.post(path + "/sessions", json={**offer(), "device_id": "helper"}).status_code == 403
    )
    assert (
        client.post(path + "/sessions", json={**offer(), "instructions": "override"}).status_code
        == 422
    )
    assert not requests
