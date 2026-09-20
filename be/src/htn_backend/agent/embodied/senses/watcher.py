"""The fast eye: checks frames for the current target while the robot keeps moving.

Robot stacks split a slow deliberate planner from a fast reactive loop (Helix, GR00T N1 and
Gemini Robotics all do). Here the planner (Codex) hands a move a `watch_for` target; this asks
the server's small vision model about each new frame in a background thread, so checking never
pauses the wheels, and the move ends early on the first confident sighting.
"""

import os
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import httpx

CONFIDENT = 0.6
TOKEN_FILE = Path(__file__).resolve().parents[6] / "robot/scripts/.robot_token"


def robot_token() -> str:
    token = os.environ.get("HTN_ROBOT_TOKEN")
    return token or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")


class Watcher:
    def __init__(self, client: httpx.Client, prefix: str):
        self.client, self.prefix = client, prefix
        self.headers = {"Authorization": f"Bearer {robot_token()}"}
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="watcher")

    def submit(self, target: str, sense) -> Future:
        """Start checking one frame; the result carries the sense it was taken from."""
        return self.pool.submit(self._check, target, sense)

    def _check(self, target: str, sense) -> dict | None:
        try:
            response = self.client.post(
                self.prefix + "/watch",
                json={"target": target, "sequence": sense.sequence},
                headers=self.headers,
                timeout=8,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None  # The eye is a shortcut, never a requirement.
        verdict = response.json()
        if not verdict.get("seen") or verdict.get("confidence", 0) < CONFIDENT:
            return None
        return dict(verdict, heading_deg=sense.heading_deg, position=sense.position)


def first_sighting(pending: list[Future]) -> dict | None:
    """The earliest finished check that saw the target; leaves unfinished ones pending."""
    for future in list(pending):
        if future.done():
            pending.remove(future)
            sighting = future.result()
            if sighting:
                return sighting
    return None
