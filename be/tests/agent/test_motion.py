"""The motion gate and link against a fake robot that follows the firmware's control rules."""

import asyncio
import json
import threading
import time

import pytest
import websockets

from htn_backend.agent.motion.link import RobotLink
from htn_backend.agent.motion.skills import Motion
from htn_backend.agent.tools import definitions


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
                self.duty = packet["drive"]["linear"] if allowed else 0.0
        finally:
            sender.cancel()

    async def _telemetry(self, ws):
        while True:
            control = {"owner": self.owner, "supervised": self.supervised, "estop": self.estop}
            frame = {
                "type": "telemetry",
                "control": control,
                "motor_duty": self.duty,
                "drivetrain": "bts7960_diff_v2",
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


def test_gate_blocks_without_supervision_and_opens_with_it(robot):
    fake, motion = robot
    assert any("not_supervised" in reason for reason in motion.blockers())
    assert not motion.status()["can_move"]
    supervise(fake, motion)
    assert motion.blockers() == [] and motion.status()["can_move"]


def test_gate_blocks_on_estop_and_wrong_firmware(robot, monkeypatch):
    fake, motion = robot
    supervise(fake, motion)
    frame, _ = motion.link.telemetry()
    wrong = dict(frame, drivetrain="single_steer_v1")
    monkeypatch.setattr(motion.link, "telemetry", lambda: (wrong, 0.0))
    assert any("drivetrain_mismatch" in reason for reason in motion.blockers())
    stopped = dict(frame, control=dict(frame["control"], estop=True))
    monkeypatch.setattr(motion.link, "telemetry", lambda: (stopped, 0.0))
    assert any("estop_latched" in reason for reason in motion.blockers())


def test_room_tools_never_include_motion():
    names = {d["name"] for d in definitions()}
    assert not names & {"drive_base", "set_arm", "run_winch", "go_to", "path"}


def test_background_heartbeat_cannot_keep_an_unrenewed_command_armed(robot):
    fake, motion = robot
    supervise(fake, motion)
    motion.link.set_command({"drive": {"linear": 0.1, "angular": 0}})
    time.sleep(0.12)
    assert any(p["armed"] for p in fake.packets)
    time.sleep(0.3)
    assert released(fake)
    assert not fake.packets[-1]["armed"]
