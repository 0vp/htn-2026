import asyncio
import base64

from fastapi.testclient import TestClient

from htn_backend.main import create_app
from htn_backend.voice.reliable.runtime import Runtime


def test_socket_resume_dedup_and_end_gap(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")

    async def conversation(self):
        self.ready = True
        await self.emit({"type": "ready"})
        await asyncio.Event().wait()

    async def finish(self, window, last):
        first, _ = window.take()
        self.journal.finalize(self.ident, first, last, "hello")

    monkeypatch.setattr(Runtime, "conversation", conversation)
    monkeypatch.setattr(Runtime, "finish_window", finish)
    with TestClient(create_app(tmp_path)) as client:
        room = client.post("/v1/rooms", json={"name": "Audio", "device_id": "phone"}).json()[
            "room_id"
        ]
        base = f"/v1/rooms/{room}/voice/reliable"
        body = {"device_id": "phone", "request_id": "request", "codex_enabled": False}
        session = client.post(base + "/sessions", json=body).json()["session_id"]
        assert client.post(base + "/sessions", json=body).json()["session_id"] == session
        url = base + f"/stream/{session}?device_id=phone"
        chunk = {"type": "audio", "seq": 0, "audio": base64.b64encode(b"\x20\x20" * 4800).decode()}
        with client.websocket_connect(url) as socket:
            assert socket.receive_json() == {"type": "ack", "next_seq": 0}
            socket.receive_json()
            socket.send_json(chunk)
            while socket.receive_json().get("type") != "ack":
                pass
        with client.websocket_connect(url) as socket:
            assert socket.receive_json() == {"type": "ack", "next_seq": 1}
            socket.send_json(chunk)
            while True:
                event = socket.receive_json()
                if event.get("type") == "ack":
                    assert event["next_seq"] == 1
                    break
        ending = {"device_id": "phone", "session_id": session, "next_seq": 2}
        assert client.post(base + "/end", json=ending).status_code == 409
        ending["next_seq"] = 1
        assert client.post(base + "/end", json=ending).status_code == 200
        assert client.post(base + "/end", json=ending).status_code == 200
