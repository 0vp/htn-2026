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
        self.duty = 0.0
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
                self.duty = packet["drive"]["duty"] if allowed else 0.0
        finally:
            sender.cancel()

    async def _telemetry(self, ws):
        while True:
            control = {"owner": self.owner, "supervised": self.supervised, "estop": self.estop}
            frame = {
                "type": "telemetry",
                "control": control,
                "motor_duty": self.duty,
                "drivetrain": "single_steer_v1",
                "encoder_ticks": 0,
                "capabilities": {"drive_base": True},
            }
            await ws.send(json.dumps(frame))
            await asyncio.sleep(0.05)


def supervise(fake, motion):
    """Arm AUTO on the fake badge and wait until the robot's telemetry reports it."""
    fake.supervised = True
    deadline = time.monotonic() + 2
    while not motion.status()["supervised_by_badge"] and time.monotonic() < deadline:
        time.sleep(0.02)


def released(fake):
    """True once the fake robot has received a disarmed packet after the move.

    The link confirms the idle packet was sent; the fake records it a moment later.
    """
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        if fake.packets and not fake.packets[-1]["armed"]:
            return True
        time.sleep(0.01)
    return False


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
    result = motion.drive_base(0.3, 0, 0.4)
    assert result["state"] == "blocked" and not result["dispatched"]
    assert any("not_supervised" in reason for reason in result["reasons"])
    assert not any(p["armed"] for p in fake.packets)


def test_supervised_drive_runs_then_releases(robot):
    fake, motion = robot
    supervise(fake, motion)
    result = motion.drive_base(0.3, 0, 0.4)
    assert result["state"] == "completed" and result["dispatched"]
    assert result["robot_reports_stopped"]
    assert (
        "not measured" in result["measurement"].lower() or "not calibrated" in result["measurement"]
    )
    armed = [p for p in fake.packets if p["armed"]]
    assert armed and all(p["drive"] == {"duty": 0.3, "steering_deg": 0} for p in armed)
    assert released(fake)


def test_losing_supervision_interrupts_the_move(robot):
    fake, motion = robot
    supervise(fake, motion)
    threading.Timer(0.4, lambda: setattr(fake, "supervised", False)).start()
    started = time.monotonic()
    result = motion.drive_base(0.2, 10, 2)
    assert result["state"] == "interrupted"
    assert result["stopped_by"].startswith("supervision_lost")
    assert time.monotonic() - started < 2
    assert released(fake)


def test_estop_interrupts_and_blocks_retry(robot):
    fake, motion = robot
    supervise(fake, motion)
    threading.Timer(0.4, lambda: setattr(fake, "estop", True)).start()
    assert motion.drive_base(0.1, 15, 2)["stopped_by"].startswith("estop")
    assert motion.drive_base(0.1, 10, 1)["state"] == "blocked"


def test_tool_bounds_reject_unsafe_arguments(robot):
    fake, motion = robot
    supervise(fake, motion)
    tools = RobotTools(None, "ABCDEF12", motion)
    assert not tools.call("drive_base", {"duty": 5, "steering_deg": 0, "seconds": 1})["success"]
    assert not tools.call("drive_base", {"duty": 0.1, "steering_deg": 90, "seconds": 1})["success"]
    assert not tools.call("run_winch", {"winch": 1, "direction": "in", "seconds": 10})["success"]
    assert not tools.call("set_arm", {})["success"]
    assert not tools.call(
        "drive_base", {"duty": 0.1, "steering_deg": 0, "seconds": 1, "shell": "rm"}
    )["success"]
    long_move = motion.drive_base(0.1, 0, 10)
    assert long_move["state"] == "rejected"
    assert not any(p["armed"] for p in fake.packets)


def test_motion_tools_are_only_offered_with_a_robot_link():
    names = {d["name"] for d in definitions()}
    assert "drive_base" not in names
    assert {"drive_base", "stop", "robot_status"} <= {d["name"] for d in definitions(motion=True)}
    assert set(motion_tools.MOTION_TOOLS) <= {d["name"] for d in definitions(motion=True)}


def test_background_heartbeat_cannot_keep_an_unrenewed_command_armed(robot):
    fake, motion = robot
    supervise(fake, motion)
    motion.link.set_command({"drive": {"duty": 0.1, "steering_deg": 0}})
    time.sleep(0.12)
    assert any(p["armed"] for p in fake.packets)
    time.sleep(0.3)
    assert released(fake)
    assert not fake.packets[-1]["armed"]


def test_missing_duty_is_unknown_not_stopped(robot, monkeypatch):
    _, motion = robot
    monkeypatch.setattr(motion.link, "telemetry", lambda: ({"type": "telemetry"}, 0.0))
    assert not motion._wait_until_still()


def test_unverified_final_stop_cannot_report_completed_motion(robot, monkeypatch):
    fake, motion = robot
    supervise(fake, motion)
    monkeypatch.setattr(motion, "_wait_until_still", lambda: False)
    result = motion.drive_base(0.3, 0, 0.4)
    assert result["state"] == "interrupted"
    assert result["stopped_by"] == "stop_not_reported"
    assert not result["physical_success"]
    assert "estimate" not in result


def test_old_differential_firmware_cannot_receive_motion(robot, monkeypatch):
    fake, motion = robot
    supervise(fake, motion)
    frame, _ = motion.link.telemetry()
    frame.pop("drivetrain")
    monkeypatch.setattr(motion.link, "telemetry", lambda: (frame, 0.0))
    result = motion.drive_base(0.1, 0, 1)
    assert result["state"] == "blocked" and not result["dispatched"]
    assert any("drivetrain_mismatch" in r for r in result["reasons"])
    assert not any(p["armed"] for p in fake.packets)
    assert "turn" not in {d["name"] for d in definitions(motion=True)}
