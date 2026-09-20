import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from htn_backend.voice.lab.server import create_app


def test_assets_no_key_and_foreign_origin(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 200
        assert "registerProcessor" in client.get("/microphone.js").text
        assert "AudioWorkletNode" in client.get("/client.js").text
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/voice", headers={"origin": "http://evil.example"}):
                pass
        with client.websocket_connect("/voice", headers={"origin": "http://testserver"}) as ws:
            assert ws.receive_json()["text"] == "Server API key is missing."


def test_reject_nonlocal_simulator():
    with pytest.raises(ValueError):
        create_app("http://robot.lan")
