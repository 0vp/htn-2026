"""Read-only bridge from teammate ESP32 firmware to a room's telemetry feed."""

import argparse
import asyncio
import json
import os
import uuid

import httpx
from websockets.asyncio.client import connect

from ..robotics.telemetry import FirmwareTelemetry, Report


async def heartbeat(socket):
    while True:
        # Firmware ignores non-command JSON but records client liveness.
        # Never arm, claim command ownership, or send drive/servo commands.
        await socket.send(json.dumps({"type": "observerHeartbeat"}))
        await asyncio.sleep(0.5)


async def bridge(room_id, robot_url, backend):
    session, sequence = uuid.uuid4().hex, 0
    async with httpx.AsyncClient(base_url=backend, timeout=3) as client:
        async with connect(robot_url, max_size=8192, open_timeout=5) as socket:
            task = asyncio.create_task(heartbeat(socket))
            try:
                async for raw in socket:
                    message = json.loads(raw)
                    if message.get("type") != "telemetry":
                        continue
                    sample = FirmwareTelemetry.model_validate(message)
                    report = Report(
                        device_id="esp32-base",
                        session_id=session,
                        sequence=sequence,
                        telemetry=sample,
                    )
                    response = await client.post(
                        f"/v1/rooms/{room_id}/robot/telemetry", json=report.model_dump()
                    )
                    response.raise_for_status()
                    sequence += 1
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(
        description="Observe ESP32 telemetry without controlling motors"
    )
    parser.add_argument("room_id", nargs="?", default="A0000001", help="Defaults to the single shared room")
    args = parser.parse_args()
    backend = os.environ.get("HTN_SERVER_URL", "https://qasim-test.35-253-10-71.sslip.io")
    robot_url = os.environ.get("HTN_ROBOT_URL", "ws://192.168.4.1:81/")
    try:
        asyncio.run(bridge(args.room_id.upper(), robot_url, backend))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
