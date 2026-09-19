"""Local WebSocket adapter for the stopped-by-default ESP32-S3 steering firmware.

Run only after flashing robot/steering. Opening a serial port can reset a board;
never attach this bridge to the old automatic startup-test sketch.
"""

import argparse
import asyncio
import contextlib
import json
import math

import serial
import websockets

STOP = dict(type="command", armed=False, estop=False)


def command(message):
    value = json.loads(message)
    if not isinstance(value, dict) or value.get("type") != "command":
        raise ValueError("Expected command")
    if type(value.get("armed")) is not bool or type(value.get("estop")) is not bool:
        raise ValueError("Explicit armed/estop booleans required")
    if not value["armed"] or value["estop"]:
        return dict(type="command", armed=False, estop=value["estop"])
    drive = value.get("drive", {})
    duty, steering = drive.get("duty"), drive.get("steering_deg")
    if not all(type(v) in (float, int) and math.isfinite(v) for v in (duty, steering)):
        raise ValueError("Finite duty and steering required")
    if abs(duty) > 0.3 or abs(steering) > 20:
        raise ValueError("Command exceeds bench limits")
    return dict(
        type="command", armed=True, estop=False, drive=dict(duty=duty, steering_deg=steering)
    )


class Bridge:
    def __init__(self, device, supervise=False):
        self.device, self.supervise = device, supervise
        self.active = False

    def send(self, value):
        self.device.write((json.dumps(value, allow_nan=False) + "\n").encode())

    async def telemetry(self, ws):
        loop = asyncio.get_running_loop()
        heard = loop.time()
        pending = b""
        while True:
            chunk = await asyncio.to_thread(self.device.read_until, b"\n", 2048)
            if loop.time() - heard > 0.5:
                raise TimeoutError("Serial telemetry stopped")
            pending += chunk
            if len(pending) > 2048:
                raise ValueError("Oversized serial telemetry")
            if not pending.endswith(b"\n"):
                continue
            line, pending = pending, b""
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("type") == "telemetry"
                and value.get("drivetrain") == "single_steer_v1"
            ):
                heard = loop.time()
                await ws.send(json.dumps(value, allow_nan=False))

    async def client(self, ws):
        if self.active:
            await ws.close(code=1008, reason="Controller already connected")
            return
        self.active = True
        sender = receiver = None
        try:
            # Check identity before forwarding any active command.
            deadline = asyncio.get_running_loop().time() + 3
            while asyncio.get_running_loop().time() < deadline:
                line = await asyncio.to_thread(self.device.read_until, b"\n", 2048)
                try:
                    state = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if (
                    isinstance(state, dict)
                    and state.get("type") == "telemetry"
                    and state.get("drivetrain") == "single_steer_v1"
                ):
                    break
            else:
                await ws.close(code=1008, reason="Steering firmware identity not verified")
                return
            self.send(STOP)
            self.send(dict(type="supervise", enabled=self.supervise))
            sender = asyncio.create_task(self.telemetry(ws))
            receiver = asyncio.create_task(self.commands(ws))
            done, _ = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (serial.SerialException, OSError, TimeoutError, ValueError):
            if receiver:
                receiver.cancel()
            with contextlib.suppress(serial.SerialException, OSError):
                self.send(STOP)
                self.send(dict(type="supervise", enabled=False))
            await ws.close(code=1011, reason="Serial control link failed")
        finally:
            with contextlib.suppress(serial.SerialException, OSError):
                self.send(STOP)
                self.send(dict(type="supervise", enabled=False))
            tasks = [task for task in (sender, receiver) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.active = False

    async def commands(self, ws):
        async for message in ws:
            try:
                value = command(message)
            except (ValueError, TypeError, AttributeError):
                self.send(STOP)
                await ws.close(code=1008, reason="Invalid steering command")
                break
            if value["armed"] and not self.supervise:
                self.send(STOP)
            else:
                self.send(value)


async def serve(device, port, supervise):
    bridge = Bridge(device, supervise)
    async with websockets.serve(bridge.client, "127.0.0.1", port, max_size=2048):
        print(f"Steering bridge ws://127.0.0.1:{port}; supervised={supervise}", flush=True)
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="Explicit serial port; never auto-scan attached boards")
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--supervise", action="store_true", help="Human-supervised bench movement")
    args = parser.parse_args()
    device = serial.Serial(
        port=None, baudrate=115200, timeout=0.05, write_timeout=0.1, exclusive=True
    )
    # Keep normal line states: forcing both false reset this CH340/ESP32-S3.
    device.port = args.device
    device.open()
    try:
        asyncio.run(serve(device, args.port, args.supervise))
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(serial.SerialException):
            device.write((json.dumps(STOP) + "\n").encode())
        device.close()


if __name__ == "__main__":
    main()
