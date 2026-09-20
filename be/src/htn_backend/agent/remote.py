"""Hand agent turns to a Codex worker running on the robot's laptop.

The server keeps speech, the room model and the tool APIs; the laptop runs Codex (signed in
there) next to the motor link, so reasoning is visible on the robot and motion stays local.

  worker:  POST /v1/agent/jobs/claim   (long poll)  -> {"job_id", "room_id", "prompt"} | 204
           POST /v1/agent/jobs/{id}/result {"result": str}
Both need `Authorization: Bearer $HTN_ROBOT_TOKEN`. While a worker has polled recently, voice
turns go to it; otherwise they run on the server's own Codex when one is installed.
"""

import asyncio
import hmac
import os
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field

PRESENT_S = 40.0
POLL_S = 25.0
JOB_TIMEOUT_S = 660.0


class Hub:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.waiting: dict[str, asyncio.Future] = {}
        self.seen = 0.0

    def present(self) -> bool:
        return time.monotonic() - self.seen <= PRESENT_S

    async def execute(self, room_id: str, prompt: str) -> str:
        job_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.waiting[job_id] = future
        await self.queue.put(dict(job_id=job_id, room_id=room_id, prompt=prompt))
        try:
            return await asyncio.wait_for(future, JOB_TIMEOUT_S)
        finally:
            self.waiting.pop(job_id, None)

    async def claim(self) -> dict | None:
        self.seen = time.monotonic()
        deadline = time.monotonic() + POLL_S
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                job = await asyncio.wait_for(self.queue.get(), remaining)
            except TimeoutError:
                break
            if job["job_id"] in self.waiting:  # Skip jobs whose caller already gave up.
                self.seen = time.monotonic()
                return job
        self.seen = time.monotonic()
        return None

    def finish(self, job_id: str, result: str) -> bool:
        future = self.waiting.get(job_id)
        if future is None or future.done():
            return False
        self.seen = time.monotonic()
        future.set_result(result)
        return True


hub = Hub()


async def execute(room_id: str, prompt: str) -> str:
    """Run one agent turn on the laptop worker when present, else on the server's Codex."""
    if hub.present():
        return await hub.execute(room_id, prompt)
    from ..voice.bridge import codex_binary
    from .motion.shared import server_motion
    from .run import run

    backend = os.environ.get("HTN_SERVER_URL", "http://127.0.0.1:8790")
    return await run(room_id, prompt, backend, codex_binary(), server_motion())


class Result(BaseModel):
    result: str = Field(max_length=20000)


def authorize(authorization: str | None) -> None:
    secret = os.environ.get("HTN_ROBOT_TOKEN", "")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(given.encode(), secret.encode()):
        raise HTTPException(403, "Worker token required")


def router() -> APIRouter:
    routes = APIRouter(prefix="/v1/agent", tags=["agent"])

    @routes.post("/jobs/claim")
    async def claim(authorization: str | None = Header(default=None)):
        authorize(authorization)
        job = await hub.claim()
        return job if job else Response(status_code=204)

    @routes.post("/jobs/{job_id}/result")
    async def result(job_id: str, body: Result, authorization: str | None = Header(default=None)):
        authorize(authorization)
        if not hub.finish(job_id, body.result):
            raise HTTPException(404, "Job is unknown or already finished")
        return {"accepted": True}

    return routes
