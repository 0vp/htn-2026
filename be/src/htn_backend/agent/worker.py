"""Laptop-side Codex worker: runs the server's voice turns on this machine's Codex.

  HTN_ROBOT_TOKEN=... python -m htn_backend.agent.worker        (or: sh agent.sh)

Claims turns from the cloud backend, runs them through the local Codex app-server (your
`codex login`), calls the cloud for room tools and the local drive.py for motion, then posts
the answer back so the phone speaks it. Codex's progress prints here.
"""

import argparse
import asyncio
import os
import shutil
import time
from pathlib import Path

import httpx

from .motion.link import RobotLink
from .motion.skills import Motion
from .run import AgentSession

CLOUD = "https://qasim-test.35-253-10-71.sslip.io"
TOKEN_FILE = Path(__file__).resolve().parents[4] / "robot/scripts/.robot_token"


def stamp(text: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


STOP_WORDS = ("stop", "halt", "freeze", "don't move", "do not move")


class Narrator:
    """Prints everything Codex does; voices the `say` lines its tools carry, as they start."""

    def __init__(self, client: httpx.AsyncClient, job_id: str, loop):
        self.client, self.job_id, self.loop = client, job_id, loop

    def __call__(self, text: str) -> None:
        stamp(text)

    def say(self, text: str) -> None:
        """Called from the tool thread the moment a move begins."""
        stamp(f"🔊 {text}")
        asyncio.run_coroutine_threadsafe(self.send(text), self.loop)

    async def send(self, text: str) -> None:
        try:
            await self.client.post(f"/v1/agent/jobs/{self.job_id}/progress", json={"result": text})
        except httpx.HTTPError:
            pass


async def work(client, session, job, motion) -> None:
    narrator = Narrator(client, job["job_id"], asyncio.get_running_loop())
    try:
        stamp("Continuing the running Codex agent" if session.server else "Starting Codex")
        if session.server is None:
            await session.start()
        session.tools.speak = narrator.say
        result = await session.turn(job["prompt"], emit=narrator)
    except asyncio.CancelledError:
        if motion:
            motion.link.release()
        result = ""  # A newer request took over; it will do the talking.
        stamp("⏹ interrupted by a newer request")
    except Exception as error:  # The phone must always get an answer.
        result = f"Something went wrong on my side ({type(error).__name__}). Ask me again."
    else:
        stamp(f"◀ {result}")
    try:
        await client.post(f"/v1/agent/jobs/{job['job_id']}/result", json={"result": result})
    except httpx.HTTPError:
        stamp("Could not deliver the result")


async def serve(backend: str, token: str, binary: str, motion: Motion | None) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    sessions: dict[str, AgentSession] = {}  # One long-lived Codex agent per room.
    running: asyncio.Task | None = None
    async with httpx.AsyncClient(base_url=backend, headers=headers, timeout=40) as client:
        stamp(f"Codex worker ready · {backend} · motion {'on' if motion else 'off'}")
        while True:
            try:
                response = await client.post("/v1/agent/jobs/claim")
                if response.status_code == 204:
                    continue
                response.raise_for_status()
            except httpx.HTTPError as error:
                stamp(f"Backend unreachable ({type(error).__name__}); retrying")
                await asyncio.sleep(3)
                continue
            job = response.json()
            stamp(f"▶ {job['prompt']}")
            spoken = job["prompt"].lower()
            if motion and any(word in spoken for word in STOP_WORDS):
                motion.link.release()  # Wheels first, reasoning second.
            if running and not running.done():
                # The newest request wins, like talking to a person: stop and listen.
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                job["prompt"] = (
                    "(You were interrupted mid-task by this new request. Wheels are stopped. "
                    "Decide whether it replaces, changes or cancels what you were doing.)\n"
                    + job["prompt"]
                )
            session = sessions.get(job["room_id"])
            if session is None:
                session = AgentSession(job["room_id"], backend, binary, motion, embodied=True)
                sessions[job["room_id"]] = session
            running = asyncio.create_task(work(client, session, job, motion))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default=os.environ.get("HTN_SERVER_URL", CLOUD))
    parser.add_argument("--robot", default=os.environ.get("HTN_ROBOT_URL", "ws://127.0.0.1:8793"))
    parser.add_argument("--no-motion", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("HTN_ROBOT_TOKEN") or (
        TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""
    )
    binary = os.environ.get("CODEX_BINARY") or shutil.which("codex")
    if not token or not binary:
        parser.error("Need HTN_ROBOT_TOKEN (or robot/scripts/.robot_token) and a logged-in codex")
    link = None
    if not args.no_motion:
        link = RobotLink(args.robot, os.environ.get("HTN_ROBOT_LOCAL_TOKEN", ""))
        link.start()
    try:
        asyncio.run(serve(args.backend, token, binary, Motion(link) if link else None))
    except KeyboardInterrupt:
        pass
    finally:
        if link:
            link.close()


if __name__ == "__main__":
    main()
