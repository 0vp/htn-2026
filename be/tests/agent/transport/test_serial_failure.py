"""USB failure must end control even when its WebSocket remains connected."""

import asyncio
import json
import time

import pytest
import serial
import websockets

from htn_backend.agent.motion.transport.serial_bridge import STOP, Bridge

STATE = {"type": "telemetry", "drivetrain": "single_steer_v1", "motor_duty": 0}


@pytest.mark.parametrize("failure", ["disconnect", "silence", "garbage"])
def test_serial_failure_closes_live_controller(failure):
    class Device:
        first = True

        def __init__(self):
            self.writes = []

        def write(self, payload):
            self.writes.append(json.loads(payload))

        def read_until(self, delimiter, maximum):
            if self.first:
                self.first = False
                return json.dumps(STATE).encode() + b"\n"
            if failure == "disconnect":
                raise serial.SerialException("Device disconnected")
            time.sleep(0.01)
            return b"bad\n" if failure == "garbage" else b""

    async def exercise():
        device = Device()
        bridge = Bridge(device, supervise=True)
        async with websockets.serve(bridge.client, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                await asyncio.wait_for(ws.wait_closed(), 2)
                assert ws.close_code == 1011
            for _ in range(50):
                if not bridge.active:
                    break
                await asyncio.sleep(0.01)
            assert not bridge.active
            assert device.writes[-2:] == [STOP, {"type": "supervise", "enabled": False}]

    asyncio.run(exercise())


def test_partial_serial_lines_reassemble():
    class Device:
        def __init__(self):
            packet = json.dumps(STATE).encode() + b"\n"
            self.parts = iter([packet[:18], b"", packet[18:]])

        def read_until(self, delimiter, maximum):
            return next(self.parts)

    class Socket:
        async def send(self, message):
            assert json.loads(message) == STATE
            raise asyncio.CancelledError()

    async def exercise():
        with pytest.raises(asyncio.CancelledError):
            await Bridge(Device()).telemetry(Socket())

    asyncio.run(exercise())
