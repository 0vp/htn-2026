"""Bounded voice sessions; key material never enters client responses."""

import asyncio
import os
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from .bridge import bridge, codex_binary


@dataclass
class Call:
    room: str
    device: str
    request_id: str
    session_id: str
    sdp: str
    codex: bool
    deadline: float
    task: asyncio.Task | None = None


class VoiceService:
    def __init__(self, store):
        self.store = store
        self.calls = {}
        self.lock = asyncio.Lock()
        self.client = httpx.AsyncClient(base_url="https://api.openai.com/v1", timeout=25)
        self.reaper = None

    def key(self):
        return os.environ.get("OPENAI_API_KEY", "").strip()

    def authorize(self, room, device, allow_closed=False):
        record = self.store.room(room)
        if (record["closed"] and not allow_closed) or record.get("leader_device_id") != device:
            raise HTTPException(403, "Only the open room's leader can use voice")

    def capabilities(self, room, device):
        self.authorize(room, device)
        return {"available": bool(self.key()), "codex_available": bool(codex_binary())}

    async def create(self, room, data):
        self.authorize(room, data.device_id)
        if not self.key() or (data.codex_enabled and not codex_binary()):
            raise HTTPException(503, "Voice or Codex is not configured")
        async with self.lock:
            for call in self.calls.values():
                if call.room == room:
                    if call.request_id == data.request_id and call.codex == data.codex_enabled:
                        return self.response(call)
                    raise HTTPException(409, "End the current voice session first")
            if len(self.calls) >= 4:
                raise HTTPException(429, "Voice capacity reached")
            instructions = (
                "You are the voice of a room robot. Be brief, warm and conversational. "
                "You can listen while speaking. Only describe task completion "
                "from verified backend results. "
            )
            instructions += (
                "Delegate room questions and tasks to Codex. "
                "Ask for clarification when the target is ambiguous."
                if data.codex_enabled
                else "Conversation-only test: Codex is disconnected. Do not claim to see the room, "
                "control a robot, or execute any task. Explain that tools are unavailable if asked."
            )
            response = await self.client.post(
                "/live/sessions",
                headers=self.headers(),
                json={
                    "session": {
                        "model": "gpt-live-1",
                        "instructions": instructions,
                        "delegation": {"type": "client"},
                    },
                    "transport": {"type": "webrtc", "sdp": data.sdp},
                },
            )
            if response.status_code != 201:
                raise HTTPException(503, "OpenAI voice session unavailable")
            result = response.json()
            call = Call(
                room,
                data.device_id,
                data.request_id,
                result["session"]["id"],
                result["transport"]["sdp"],
                data.codex_enabled,
                time.monotonic() + 600,
            )
            self.calls[call.session_id] = call
            if self.reaper is None:
                self.reaper = asyncio.create_task(self.reap())
            ready = asyncio.Event()
            call.task = asyncio.create_task(self.monitor(call, ready))
            try:
                await asyncio.wait_for(ready.wait(), timeout=18)
            except BaseException:
                await self.end(call.session_id)
                raise
            return self.response(call)

    def headers(self):
        return {"Authorization": f"Bearer {self.key()}"}

    @staticmethod
    def response(call):
        return {"session_id": call.session_id, "sdp": call.sdp, "codex_enabled": call.codex}

    async def monitor(self, call, ready):
        try:
            await bridge(call.session_id, self.key(), call.room, call.codex, ready)
        except Exception:
            pass
        finally:
            if call.session_id in self.calls:
                await self.end(call.session_id, cancel=False)

    async def end(self, ident, cancel=True):
        call = self.calls.pop(ident, None)
        if call is None:
            return
        # Stop delegated work immediately, even when provider hangup is slow.
        if cancel and call.task:
            call.task.cancel()
            await asyncio.gather(call.task, return_exceptions=True)
        try:
            response = await self.client.post(
                f"/live/sessions/{quote(ident, safe='')}/hangup", headers=self.headers()
            )
            if response.status_code not in {200, 204, 404, 410}:
                raise HTTPException(503, "Voice hangup not confirmed")
        except BaseException:
            self.calls[ident] = call
            call.deadline = 0  # Reaper retries cleanup; never resume the agent.
            raise

    async def reap(self):
        while True:
            await asyncio.sleep(10)
            for call in list(self.calls.values()):
                if time.monotonic() >= call.deadline:
                    try:
                        await self.end(call.session_id)
                    except Exception:
                        pass

    async def close(self):
        if self.reaper:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
        for ident in list(self.calls):
            try:
                await self.end(ident)
            except Exception:
                call = self.calls.pop(ident, None)
                if call and call.task:
                    call.task.cancel()
        await self.client.aclose()
