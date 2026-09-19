"""Motion tools against a fake robot that follows the firmware's control rules (authority.cpp)."""

import asyncio
import json
import threading
import time

import pytest
import websockets

from htn_backend.agent.motion import tools as motion_tools
from htn_backend.agent.motion.link import RobotLink
from htn_backend.agent.motion.skills import Motion
from htn_backend.agent.tools import RobotTools, definitions


class FakeRobot:
    """Grants the agent control only while `supervised`, like a badge armed in AUTO."""

    def __init__(self):
        self.supervised = False
        self.estop = False
        self.owner = "none"
        self.duty = {"left": 0.0, "right": 0.0}
        self.packets: list[dict] = []
        self.paths: list[str] = []
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()
        self.ready.wait(5)

    def _serve(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self):
        async with websockets.serve(self._client, "127.0.0.1", 0) as server:
            self.port = server.sockets[0].getsockname()[1]
            self.ready.set()
            await asyncio.Future()

    async def _client(self, ws):
        self.paths.append(ws.request.path)
        sender = asyncio.create_task(self._telemetry(ws))
        try:
            async for message in ws:
                packet = json.loads(message)
                self.packets.append(packet)
                allowed = packet["armed"] and self.supervised and not self.estop
                self.owner = "agent" if allowed else "none"
                self.duty = packet["drive"] if allowed else {"left": 0.0, "right": 0.0}
        finally:
            sender.cancel()

    async def _telemetry(self, ws):
        while True:
            control = {"owner": self.owner, "supervised": self.supervised, "estop": self.estop}
            frame = {"type": "telemetry", "control": control, "duty": self.duty}
            frame["encoders"] = {"left": 0, "right": 0}
            await ws.send(json.dumps(frame))
            await asyncio.sleep(0.05)


def supervise(fake, motion):
    """Arm AUTO on the fake badge and wait until the robot's telemetry reports it."""
    fake.supervised = True
    deadline = time.monotonic() + 2
    while not motion.status()["supervised_by_badge"] and time.monotonic() < deadline:
        time.sleep(0.02)


@pytest.fixture
def robot():
    fake = FakeRobot()
    link = RobotLink(f"ws://127.0.0.1:{fake.port}", "secret token")
    link.start()
    deadline = time.monotonic() + 5
    while link.telemetry()[1] > 0.5 and time.monotonic() < deadline:
        time.sleep(0.05)
    yield fake, Motion(link)
    link.close()


def test_link_sends_token_and_idles_disarmed(robot):
    fake, _ = robot
    assert fake.paths[0] == "/?token=secret%20token"
    time.sleep(0.2)
    assert fake.packets and all(p["source"] == "agent" and not p["armed"] for p in fake.packets)


def test_motion_is_blocked_without_badge_supervision(robot):
    fake, motion = robot
    result = motion.drive(0.02, 0.3)
    assert result["state"] == "blocked" and not result["dispatched"]
    assert any("not_supervised" in reason for reason in result["reasons"])
    assert not any(p["armed"] for p in fake.packets)


def test_supervised_drive_runs_then_releases(robot):
    fake, motion = robot
    supervise(fake, motion)
    result = motion.drive(0.02, 0.3)
    assert result["state"] == "completed" and result["dispatched"]
    assert result["robot_reports_stopped"]
    assert "not measured" in result["measurement"].lower() or "estimated" in result["measurement"]
    armed = [p for p in fake.packets if p["armed"]]
    assert armed and all(p["drive"] == {"left": 0.3, "right": 0.3} for p in armed)
    assert not fake.packets[-1]["armed"]


def test_losing_supervision_interrupts_the_move(robot):
    fake, motion = robot
    supervise(fake, motion)
    threading.Timer(0.4, lambda: setattr(fake, "supervised", False)).start()
    started = time.monotonic()
    result = motion.drive(0.2, 0.2)
    assert result["state"] == "interrupted"
    assert result["stopped_by"].startswith("supervision_lost")
    assert time.monotonic() - started < 2
    assert not fake.packets[-1]["armed"]


def test_estop_interrupts_and_blocks_retry(robot):
    fake, motion = robot
    supervise(fake, motion)
    threading.Timer(0.4, lambda: setattr(fake, "estop", True)).start()
    assert motion.turn(90, 0.1)["stopped_by"].startswith("estop")
    assert motion.turn(10, 0.1)["state"] == "blocked"


def test_tool_bounds_reject_unsafe_arguments(robot):
    fake, motion = robot
    supervise(fake, motion)
    tools = RobotTools(None, "ABCDEF12", motion)
    assert not tools.call("drive", {"distance_m": 5})["success"]
    assert not tools.call("drive", {"distance_m": 0.1, "speed": 1.0})["success"]
    assert not tools.call("run_winch", {"winch": 1, "direction": "in", "seconds": 10})["success"]
    assert not tools.call("set_arm", {})["success"]
    assert not tools.call("drive", {"distance_m": 0.1, "shell": "rm"})["success"]
    long_move = json.loads(
        tools.call("drive", {"distance_m": 1.0, "speed": 0.05})["contentItems"][0]["text"]
    )
    assert long_move["state"] == "rejected"
    assert not any(p["armed"] for p in fake.packets)


def test_motion_tools_are_only_offered_with_a_robot_link():
    names = {d["name"] for d in definitions()}
    assert "drive" not in names
    assert {"drive", "turn", "stop", "robot_status"} <= {
        d["name"] for d in definitions(motion=True)
    }
    assert set(motion_tools.MOTION_TOOLS) <= {d["name"] for d in definitions(motion=True)}
