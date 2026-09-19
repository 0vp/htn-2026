"""Badge AUTO heartbeat -> bridge supervision -> agent tool -> actual firmware protocol."""

import asyncio
import contextlib
import json
import time

import pytest
import websockets

from htn_backend.agent.motion.link import RobotLink
from htn_backend.agent.motion.skills import Motion
from htn_backend.agent.motion.transport.serial_bridge import Bridge, badge_packet

TOKEN = "badge-secret"


def packet(estop=False, armed=True, auto=True, source="badge"):
    # Manual drive fields are deliberately large: the bridge must never forward them.
    return json.dumps(
        {
            "type": "command",
            "seq": 1,
            "t": 0,
            "estop": estop,
            "armed": armed,
            "drive": {"left": 0.9, "right": 0.9},
            "arm": {"shoulder": 0, "elbow": 0, "wrist": 0},
            "winch": [0, 0, 0],
            "goal": None,
            "source": source,
            "auto": auto,
        }
    )


def port(server):
    return server.sockets[0].getsockname()[1]


async def until(check, seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        await asyncio.sleep(0.02)
    return False


@contextlib.asynccontextmanager
async def rig(firmware):
    bridge = Bridge(firmware, badge_token=TOKEN)
    async with (
        websockets.serve(bridge.client, "127.0.0.1", 0) as agent_server,
        websockets.serve(bridge.badge_client, "127.0.0.1", 0) as badge_server,
    ):
        link = RobotLink(f"ws://127.0.0.1:{port(agent_server)}", "")
        link.start()
        try:
            assert await until(lambda: link.telemetry()[1] < 0.2)
            yield bridge, link, f"ws://127.0.0.1:{port(badge_server)}/?token={TOKEN}"
        finally:
            await asyncio.to_thread(link.close)


@contextlib.asynccontextmanager
async def heartbeat(url, message):
    """Streams one badge packet at the badge's 20 Hz until the block exits."""
    async with websockets.connect(url) as ws:

        async def beat():
            while True:
                await ws.send(message)
                await asyncio.sleep(0.05)

        task = asyncio.create_task(beat())
        try:
            yield ws
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def supervised(link):
    return link.telemetry()[0].get("control", {}).get("supervised") is True


def test_agent_is_blocked_without_badge(firmware):
    async def exercise():
        async with rig(firmware) as (_, link, _url):
            result = await asyncio.to_thread(Motion(link).drive_base, 0.2, 0, 0.5)
            assert result["state"] == "blocked" and not result["dispatched"]
            assert any(r.startswith("not_supervised") for r in result["reasons"])

    asyncio.run(exercise())


def test_badge_auto_supervises_agent_motion(firmware):
    async def exercise():
        async with rig(firmware) as (_, link, url), heartbeat(url, packet()) as badge:
            assert await until(lambda: supervised(link))
            # The badge also receives the robot's telemetry, which keeps its link alive.
            assert json.loads(await asyncio.wait_for(badge.recv(), 1))["type"] == "telemetry"
            result = await asyncio.to_thread(Motion(link).drive_base, 0.2, 5, 0.5)
            assert result["state"] == "completed" and result["dispatched"]
            assert result["robot_reports_stopped"] and not result["physical_success"]
            assert link.telemetry()[0]["steering_deg"] == 5

    asyncio.run(exercise())


@pytest.mark.parametrize("message", [packet(auto=False), packet(armed=False)])
def test_manual_or_disarmed_badge_does_not_supervise(firmware, message):
    async def exercise():
        async with rig(firmware) as (_, link, url), heartbeat(url, message):
            assert not await until(lambda: supervised(link), 0.6)
            result = await asyncio.to_thread(Motion(link).drive_base, 0.2, 0, 0.5)
            assert result["state"] == "blocked"

    asyncio.run(exercise())


def test_silent_badge_interrupts_motion(firmware):
    async def exercise():
        async with rig(firmware) as (_, link, url):
            async with websockets.connect(url) as ws:
                beat = asyncio.create_task(heartbeat_until_cancelled(ws))
                assert await until(lambda: supervised(link))
                motion = asyncio.create_task(
                    asyncio.to_thread(Motion(link).drive_base, 0.2, 0, 2.0)
                )
                await asyncio.sleep(0.5)
                beat.cancel()  # Socket stays open; only the heartbeat stops.
                result = await motion
            assert result["state"] == "interrupted"
            assert result["stopped_by"].startswith("supervision_lost")
            assert result["ran_seconds"] < 1.5
            assert link.telemetry()[0]["motor_duty"] == 0

    asyncio.run(exercise())


async def heartbeat_until_cancelled(ws):
    while True:
        await ws.send(packet())
        await asyncio.sleep(0.05)


def test_badge_estop_latches_in_firmware(firmware):
    async def exercise():
        async with rig(firmware) as (_, link, url):
            async with heartbeat(url, packet()):
                assert await until(lambda: supervised(link))
            async with websockets.connect(url) as ws:
                await ws.send(packet(estop=True))
                assert await until(lambda: link.telemetry()[0]["control"]["estop"])
            # Re-arming AUTO cannot clear a firmware latch; only a board reset does.
            async with heartbeat(url, packet()):
                await asyncio.sleep(0.4)
                result = await asyncio.to_thread(Motion(link).drive_base, 0.2, 0, 0.5)
            assert result["state"] == "blocked"
            assert any(r.startswith("estop_latched") for r in result["reasons"])

    asyncio.run(exercise())


@pytest.mark.parametrize("query", ["", "?token=wrong"])
def test_badge_endpoint_requires_token(firmware, query):
    async def exercise():
        async with rig(firmware) as (_, link, url):
            async with websockets.connect(url.split("/?")[0] + "/" + query) as ws:
                with contextlib.suppress(websockets.ConnectionClosed):
                    await ws.send(packet())  # Rejected before or after this lands.
                await asyncio.wait_for(ws.wait_closed(), 1)
                assert ws.close_code == 1008
            assert not supervised(link)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "message",
    [
        "[]",
        packet(source="agent"),
        packet(source="dashboard"),
        json.dumps({"type": "command", "source": "badge", "estop": False, "armed": True}),
        json.dumps({"type": "command", "source": "badge", "estop": 0, "armed": 1, "auto": 1}),
    ],
)
def test_only_explicit_badge_packets_count(message):
    with pytest.raises((ValueError, TypeError)):
        badge_packet(message)


def test_badge_packet_reading():
    assert badge_packet(packet()) == (False, True)
    assert badge_packet(packet(auto=False)) == (False, False)
    assert badge_packet(packet(estop=True)) == (True, False)
