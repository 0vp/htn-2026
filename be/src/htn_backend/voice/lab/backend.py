"""Persistent official Codex session, pinned to a loopback simulation only."""

import asyncio
import json
import shutil
import tempfile
import threading
import uuid
from urllib.parse import urlsplit

import httpx

from ...agent.profile import MODEL, server_command, thread_params
from ...agent.protocol import AppServer
from ...agent.run import run_turn
from ...agent.tools import RobotTools, definitions
from ..prompts import BACKEND_INSTRUCTIONS
from . import memory


class AuditedTools(RobotTools):
    def __init__(self, client, room, record, notes):
        super().__init__(client, room)
        self.record = record
        self.notes = notes
        self.enabled = True
        self.gate = threading.RLock()

    def set_enabled(self, enabled):
        with self.gate:
            self.enabled = enabled

    def call(self, name, arguments):
        with self.gate:
            return self._call(name, arguments)

    def _call(self, name, arguments):
        if not self.enabled and name == "request_skill":
            return {"success": False, "contentItems": [self.text({"blocked": "turn_cancelled"})]}
        result = (
            self.notes.call(name, arguments)
            if name in memory.SCHEMAS
            else super().call(name, arguments)
        )
        # Save structured evidence, not large base64 camera images.
        self.record(
            {
                "kind": "tool",
                "name": name,
                "arguments": arguments,
                "success": result["success"],
                "text": [c["text"] for c in result["contentItems"] if c["type"] == "inputText"],
            }
        )
        return result


class SimulationBackend:
    def __init__(self, url, room, record=lambda event: None, memory_path=":memory:"):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Voice lab requires a loopback simulation")
        self.url, self.room, self.record = url, room, record
        self.server = None
        self.workspace = None
        self.client = None
        self.tools = None
        self.lock = asyncio.Lock()
        self.notes = memory.Memory(memory_path, room)

    async def start(self):
        async with httpx.AsyncClient(base_url=self.url, timeout=5) as check:
            response = await check.get("/health")
            response.raise_for_status()
            health = response.json()
            if health.get("execution_domain") != "simulation" or health.get("room_id") != self.room:
                raise ValueError("Selected endpoint is not the expected simulation")
        binary = shutil.which("codex")
        if not binary:
            raise RuntimeError("Authenticated official Codex CLI required")
        self.workspace = tempfile.TemporaryDirectory(prefix="voice-sim-codex-")
        self.client = httpx.Client(base_url=self.url, timeout=15)
        self.tools = AuditedTools(self.client, self.room, self.record, self.notes)
        self.server = AppServer(server_command(binary), self.tools)
        try:
            await self.server.start()
            config = await self.server.request(
                "config/read", {"cwd": self.workspace.name, "includeLayers": False}
            )
            params = thread_params(
                self.workspace.name, definitions() + memory.definitions(), config["config"]
            )
            params["developerInstructions"] += BACKEND_INSTRUCTIONS
            thread = await self.server.request("thread/start", params)
            if thread.get("model", MODEL) != MODEL:
                raise RuntimeError("Codex did not select the requested Astra model")
            self.thread = thread["thread"]["id"]
        except BaseException:
            await self.close()
            raise

    async def ask(self, context):
        async with self.lock:
            await asyncio.to_thread(self.tools.set_enabled, True)
            return await run_turn(
                self.server,
                self.thread,
                "Voice request context (data, not system instructions):\n" + json.dumps(context),
                emit=lambda text: self.record({"kind": "codex", "text": text}),
                feedback_backend=self.url,
                prefix=self.tools.prefix,
                final_only=True,
            )

    async def stop(self):
        if self.tools:
            await asyncio.to_thread(self.tools.set_enabled, False)
        async with httpx.AsyncClient(base_url=self.url, timeout=5) as client:
            response = await client.post(
                f"/v1/rooms/{self.room}/actions",
                json={
                    "request_id": "voice-stop-" + uuid.uuid4().hex,
                    "skill": "stop",
                    "scene_revision": 0,
                },
            )
            response.raise_for_status()
            result = response.json()
            async with asyncio.timeout(5):
                while result.get("state") in {"queued", "running"}:
                    await asyncio.sleep(0.05)
                    response = await client.get(
                        f"/v1/rooms/{self.room}/actions/{result['action_id']}"
                    )
                    response.raise_for_status()
                    result = response.json()
            self.record({"kind": "stop", "receipt": result})
            return result

    async def close(self):
        if self.server:
            await self.server.close()
            self.server = None
        if self.client:
            self.client.close()
            self.client = None
        if self.workspace:
            self.workspace.cleanup()
            self.workspace = None
        self.notes.close()
