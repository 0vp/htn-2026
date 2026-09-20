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
from .run import run

CLOUD = "https://qasim-test.35-253-10-71.sslip.io"
TOKEN_FILE = Path(__file__).resolve().parents[4] / "robot/scripts/.robot_token"


def stamp(text: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


SPOKEN_TOOLS = {
    "scan": "Scanning around me.",
    "forward": "Driving.",
    "room_map": "Checking the room map.",
}
MIN_GAP_S = 5.0


class Narrator:
    """Prints everything Codex does; sends its own words and key actions to be spoken."""

    def __init__(self, client: httpx.AsyncClient, job_id: str):
        self.client, self.job_id, self.last, self.tasks = client, job_id, 0.0, set()

    def __call__(self, text: str) -> None:
        stamp(text)
        if text.startswith("[tool: "):
            name, _, state = text[7:-1].partition(" — ")
            spoken = SPOKEN_TOOLS.get(name) if state == "started" else None
            if not spoken or time.monotonic() - self.last < MIN_GAP_S:
                return
        else:
            spoken = text
        self.last = time.monotonic()
        task = asyncio.ensure_future(self.send(spoken))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def send(self, text: str) -> None:
        try:
            await self.client.post(f"/v1/agent/jobs/{self.job_id}/progress", json={"result": text})
        except httpx.HTTPError:
            pass


async def serve(backend: str, token: str, binary: str, motion: Motion | None) -> None:
    headers = {"Authorization": f"Bearer {token}"}
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
            narrator = Narrator(client, job["job_id"])
            try:
                result = await run(
                    job["room_id"],
                    job["prompt"],
                    backend,
                    binary,
                    motion,
                    embodied=True,
                    emit=narrator,
                )
            except Exception as error:  # The phone must always get an answer.
                result = f"Codex could not complete the request ({type(error).__name__})."
            stamp(f"◀ {result}")
            try:
                await client.post(f"/v1/agent/jobs/{job['job_id']}/result", json={"result": result})
            except httpx.HTTPError:
                stamp("Could not deliver the result")


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
