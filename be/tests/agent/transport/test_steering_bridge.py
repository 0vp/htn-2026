"""Agent tool -> WebSocket -> serial bridge -> actual native firmware protocol."""

import asyncio

import pytest
import websockets

from htn_backend.agent.motion.link import RobotLink
from htn_backend.agent.motion.skills import Motion
from htn_backend.agent.motion.transport.serial_bridge import Bridge, command


@pytest.mark.parametrize("supervised", [False, True])
def test_bounded_motion_through_native_serial_protocol(firmware, supervised):
    async def exercise():
        bridge = Bridge(firmware, supervise=supervised)
        async with websockets.serve(bridge.client, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            link = RobotLink(f"ws://127.0.0.1:{port}", "")
            link.start()
            try:
                for _ in range(100):
                    if link.telemetry()[1] < 0.2:
                        break
                    await asyncio.sleep(0.02)
                motion = Motion(link)
                result = await asyncio.to_thread(motion.drive_base, 0.2, -15, 0.5)
                if supervised:
                    assert result["state"] == "completed"
                    assert result["dispatched"] and result["robot_reports_stopped"]
                    assert not result["physical_success"]
                    assert result["encoder_counts_delta"] == 0
                    assert link.telemetry()[0]["steering_deg"] == -15
                    # Background link stays alive but cannot prolong a stalled caller's command.
                    link.set_command({"drive": {"duty": 0.1, "steering_deg": 0}})
                    await asyncio.sleep(0.65)
                    assert link.telemetry()[0]["motor_duty"] == 0
                else:
                    assert result["state"] == "blocked"
                    assert not result["dispatched"]
            finally:
                await asyncio.to_thread(link.close)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "message",
    [
        "[]",
        "{}",
        '{"type":"supervise","enabled":true}',
        '{"type":"command","armed":true,"estop":false,"drive":{"left":1,"right":-1}}',
        '{"type":"command","armed":true,"estop":false,"drive":{"duty":0.5,"steering_deg":0}}',
        '{"type":"command","armed":true,"estop":false,"drive":{"duty":0.1,"steering_deg":NaN}}',
    ],
)
def test_invalid_or_privileged_packets_never_forward(message):
    with pytest.raises((ValueError, AttributeError)):
        command(message)
