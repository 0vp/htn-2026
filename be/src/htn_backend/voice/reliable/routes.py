"""A room-scoped, resumable audio upload protocol, separate from camera traffic."""

import asyncio
import base64
import time
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ...api.models import DeviceID, RoomID
from .journal import Journal
from .runtime import Runtime


class Start(BaseModel):
    device_id: DeviceID
    request_id: str = Field(min_length=1, max_length=80)
    codex_enabled: bool = True


class Finish(BaseModel):
    device_id: DeviceID
    session_id: str
    next_seq: int = Field(ge=0)


class ReliableVoice:
    def __init__(self, service, path):
        self.service = service
        self.journal = Journal(path)
        self.journal.prune()
        self.calls = {}
        self.reaper = None
        # One lock serializes SQLite access, including worker reads/writes via wrapper.

    def start(self):
        if self.reaper is None:
            self.reaper = asyncio.create_task(self.reap())

    async def reap(self):
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(self.journal.prune)
            for ident, call in list(self.calls.items()):
                if time.monotonic() >= call.deadline:
                    await call.emit(
                        {"type": "fatal", "text": "Voice session ended; saved audio retained."}
                    )
                    await call.close()
                    self.calls.pop(ident, None)

    def runtime(self, ident, room, device):
        saved_room, saved_device, _, ended = self.journal.session(ident)
        if (room, device) != (saved_room, saved_device):
            raise HTTPException(403, "Audio session belongs to another device")
        if ended:
            raise HTTPException(409, "Audio session already ended")
        if ident not in self.calls:
            if len(self.calls) >= 8:
                raise HTTPException(429, "Voice is busy")
            self.calls[ident] = Runtime(self.service, self.journal, ident)
        return self.calls[ident]

    async def close(self):
        if self.reaper:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
        await asyncio.gather(*(call.close() for call in self.calls.values()))
        self.journal.close()


def router(reliable):
    routes = APIRouter(prefix="/v1/rooms/{room_id}/voice/reliable", tags=["voice"])

    @routes.post("/sessions")
    async def start(room_id: RoomID, data: Start):
        reliable.service.authorize(room_id, data.device_id)
        reliable.start()
        cap = reliable.service.capabilities(room_id, data.device_id)
        if not cap["available"] or data.codex_enabled and not cap["codex_available"]:
            raise HTTPException(503, "Voice or Codex unavailable")
        ident = reliable.journal.create(
            "buffered-" + uuid.uuid4().hex,
            room_id,
            data.device_id,
            data.request_id,
            data.codex_enabled,
        )
        if bool(reliable.journal.session(ident)[2]) != data.codex_enabled:
            raise HTTPException(409, "Finish pending audio before changing Codex mode")
        reliable.journal.reopen(ident)
        reliable.runtime(ident, room_id, data.device_id)
        return {"session_id": ident, "sdp": ident, "codex_enabled": data.codex_enabled}

    @routes.websocket("/stream/{ident}")
    async def stream(socket: WebSocket, room_id: RoomID, ident: str, device_id: DeviceID):
        try:
            reliable.service.authorize(room_id, device_id)
            call = reliable.runtime(ident, room_id, device_id)
        except (HTTPException, ValueError):
            await socket.close(code=1008)
            return
        await socket.accept()
        if call.browser:
            await call.browser.close(code=1000)
        call.browser = socket
        try:
            await call.emit({"type": "ack", "next_seq": reliable.journal.next_seq(ident)})
            await call.emit({"type": "final", "turns": reliable.journal.snapshot(ident)})
            if call.ready:
                await call.emit({"type": "ready"})
            call.start()
            while True:
                event = await socket.receive_json()
                if event.get("type") != "audio":
                    raise ValueError("Expected audio chunk")
                if len(event.get("audio", "")) > 32000:
                    raise ValueError("Audio chunk too large")
                pcm = base64.b64decode(event["audio"], validate=True)
                seq = await asyncio.to_thread(reliable.journal.append, ident, event.get("seq"), pcm)
                await call.emit({"type": "ack", "next_seq": seq})
        except WebSocketDisconnect:
            pass
        except (ValueError, KeyError):
            await socket.send_json(
                {"type": "fatal", "text": "Audio sequence invalid; local recording retained."}
            )
            await socket.close(code=1008)
        finally:
            if call.browser is socket:
                call.browser = None

    @routes.post("/end")
    async def finish(room_id: RoomID, data: Finish):
        reliable.service.authorize(room_id, data.device_id, allow_closed=True)
        saved_room, saved_device, _, ended = reliable.journal.session(data.session_id)
        if (room_id, data.device_id) != (saved_room, saved_device):
            raise HTTPException(403, "Audio session belongs to another device")
        if ended:
            return {"ended": True, "turns": reliable.journal.snapshot(data.session_id)}
        call = reliable.runtime(data.session_id, room_id, data.device_id)
        if reliable.journal.next_seq(data.session_id) != data.next_seq:
            raise HTTPException(409, "Audio still waiting to upload")
        await call.close()
        if reliable.journal.completed(data.session_id) != data.next_seq:
            call.failed = True
            raise HTTPException(503, "Audio saved; transcription still pending")
        reliable.journal.end(data.session_id)
        reliable.calls.pop(data.session_id, None)
        return {"ended": True, "turns": reliable.journal.snapshot(data.session_id)}

    return routes
