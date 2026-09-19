"""Local WebSocket adapter for the stopped-by-default ESP32-S3 steering firmware.

Run only after flashing robot/steering. Opening a serial port can reset a board;
never attach this bridge to the old automatic startup-test sketch.

One serial reader feeds two endpoints:
- Controller (loopback only): the agent's RobotLink sends bounded drive commands.
- Badge (optional, token-guarded): the handheld badge supervises. While it is armed in AUTO
  its packets are a heartbeat, and only while that heartbeat is fresh is the firmware told
  it is supervised. A badge E-STOP is forwarded and latches in firmware until the board is
  reset. The badge never commands motion through this bridge.
"""

import argparse
import asyncio
import contextlib
import hmac
import json
import math
import os
import time
from urllib.parse import parse_qs, urlsplit

import serial
import websockets

STOP = dict(type="command", armed=False, estop=False)
ESTOP = dict(type="command", armed=False, estop=True)
TELEMETRY_SILENCE_S = 0.5
IDENTITY_TIMEOUT_S = 3.0
# Same as the firmware's motor watchdog: a silent badge ends supervision as quickly as a
# silent host ends a command.
BADGE_FRESH_S = 0.3
SUPERVISE_REFRESH_S = 0.2
TICK_S = 0.05
QUEUE_SIZE = 8


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


def badge_packet(message) -> tuple[bool, bool]:
    """Reads a badge command packet (badge/README.md) as (estop, supervising).

    Only its safety fields are used; drive, arm and winch values are ignored.
    """
    value = json.loads(message)
    if (
        not isinstance(value, dict)
        or value.get("type") != "command"
        or value.get("source") != "badge"
    ):
        raise ValueError("Expected badge command")
    estop, armed, auto = value.get("estop"), value.get("armed"), value.get("auto")
    if not all(type(v) is bool for v in (estop, armed, auto)):
        raise ValueError("Explicit estop/armed/auto booleans required")
    return estop, auto and armed and not estop


def telemetry_line(line: bytes) -> str | None:
    try:
        value = json.loads(line)
        if (
            isinstance(value, dict)
            and value.get("type") == "telemetry"
            and value.get("drivetrain") == "single_steer_v1"
        ):
            return json.dumps(value, allow_nan=False)
    except (ValueError, UnicodeError):
        pass
    return None


class Bridge:
    def __init__(self, device, supervise=False, badge_token=None):
        self.device, self.supervise = device, supervise
        self.badge_token = badge_token
        self.active = False
        self.badge_active = False
        self.badge_seen: float | None = None
        self.heard: float | None = None
        self.failure: Exception | None = None
        self.listeners: set[asyncio.Queue] = set()
        self.pump_task: asyncio.Task | None = None
        self.supervising_sent: bool | None = None
        self.synced_at = 0.0

    def send(self, value):
        self.device.write((json.dumps(value, allow_nan=False) + "\n").encode())

    def supervised(self) -> bool:
        """Supervision is granted only to a live controller session."""
        if not self.active:
            return False
        if self.supervise:
            return True
        seen = self.badge_seen
        return seen is not None and time.monotonic() - seen <= BADGE_FRESH_S

    def sync_supervision(self, force=False):
        want, now = self.supervised(), time.monotonic()
        if force or want != self.supervising_sent or now - self.synced_at >= SUPERVISE_REFRESH_S:
            self.send(dict(type="supervise", enabled=want))
            self.supervising_sent, self.synced_at = want, now

    def ensure_pump(self):
        if self.pump_task is None or self.pump_task.done():
            self.failure = None
            self.pump_task = asyncio.create_task(self.pump())

    async def pump(self):
        """Sole serial reader; fans valid telemetry out to every connected endpoint."""
        pending = b""
        try:
            while True:
                pending += await asyncio.to_thread(self.device.read_until, b"\n", 2048)
                if len(pending) > 2048:
                    pending = b""  # Oversized line: drop it; silence detection ends control.
                    continue
                if not pending.endswith(b"\n"):
                    continue
                line, pending = pending, b""
                state = telemetry_line(line)
                if state is None:
                    continue
                self.heard = time.monotonic()
                for queue in self.listeners:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(state)
        except (serial.SerialException, OSError) as error:
            self.failure = error

    async def forward(self, ws, queue):
        while True:
            await ws.send(await queue.get())

    async def watch(self):
        while True:
            if self.failure:
                raise self.failure
            if self.heard is None or time.monotonic() - self.heard > TELEMETRY_SILENCE_S:
                raise TimeoutError("Serial telemetry stopped")
            self.sync_supervision()
            await asyncio.sleep(TICK_S)

    async def client(self, ws):
        if self.active:
            await ws.close(code=1008, reason="Controller already connected")
            return
        self.active = True
        queue: asyncio.Queue = asyncio.Queue(QUEUE_SIZE)
        tasks: list[asyncio.Task] = []
        try:
            self.ensure_pump()
            self.listeners.add(queue)
            # Check identity before forwarding any active command.
            started = time.monotonic()
            while self.heard is None or self.heard < started:
                if self.failure:
                    raise self.failure
                if time.monotonic() - started > IDENTITY_TIMEOUT_S:
                    await ws.close(code=1008, reason="Steering firmware identity not verified")
                    return
                await asyncio.sleep(0.02)
            self.send(STOP)
            self.sync_supervision(force=True)
            tasks = [
                asyncio.create_task(self.forward(ws, queue)),
                asyncio.create_task(self.commands(ws)),
                asyncio.create_task(self.watch()),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (serial.SerialException, OSError, TimeoutError, ValueError):
            for task in tasks:
                task.cancel()
            with contextlib.suppress(serial.SerialException, OSError):
                self.send(STOP)
                self.send(dict(type="supervise", enabled=False))
            await ws.close(code=1011, reason="Serial control link failed")
        except websockets.ConnectionClosed:
            pass
        finally:
            self.active = False
            self.listeners.discard(queue)
            with contextlib.suppress(serial.SerialException, OSError):
                self.send(STOP)
                self.send(dict(type="supervise", enabled=False))
            self.supervising_sent = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def commands(self, ws):
        async for message in ws:
            try:
                value = command(message)
            except (ValueError, TypeError, AttributeError):
                self.send(STOP)
                await ws.close(code=1008, reason="Invalid steering command")
                break
            if value["armed"] and not self.supervised():
                self.send(STOP)
            else:
                self.send(value)

    def badge_allowed(self, ws) -> bool:
        if not self.badge_token:
            return False
        query = parse_qs(urlsplit(ws.request.path).query)
        given = (query.get("token") or [""])[0]
        return hmac.compare_digest(given.encode(), self.badge_token.encode())

    async def badge_client(self, ws):
        if not self.badge_allowed(ws):
            await ws.close(code=1008, reason="Badge token required")
            return
        if self.badge_active:
            await ws.close(code=1008, reason="Badge already connected")
            return
        self.badge_active = True
        queue: asyncio.Queue = asyncio.Queue(QUEUE_SIZE)
        forward = None
        try:
            self.ensure_pump()
            self.listeners.add(queue)
            forward = asyncio.create_task(self.forward(ws, queue))
            async for message in ws:
                try:
                    estop, supervising = badge_packet(message)
                except (ValueError, TypeError):
                    self.badge_seen = None  # Anything unexpected withdraws supervision.
                    continue
                if estop:
                    self.badge_seen = None
                    self.send(ESTOP)
                else:
                    self.badge_seen = time.monotonic() if supervising else None
        except (serial.SerialException, OSError):
            await ws.close(code=1011, reason="Serial control link failed")
        except websockets.ConnectionClosed:
            pass
        finally:
            self.badge_seen = None
            self.badge_active = False
            self.listeners.discard(queue)
            if forward:
                forward.cancel()
                await asyncio.gather(forward, return_exceptions=True)


async def serve(device, port, supervise, badge_port=None, badge_host="0.0.0.0", badge_token=None):
    bridge = Bridge(device, supervise, badge_token)
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(
            websockets.serve(bridge.client, "127.0.0.1", port, max_size=2048)
        )
        summary = f"Steering bridge ws://127.0.0.1:{port}; supervised={supervise}"
        if badge_port:
            await stack.enter_async_context(
                websockets.serve(bridge.badge_client, badge_host, badge_port, max_size=1024)
            )
            summary = (
                f"Steering bridge ws://127.0.0.1:{port}; supervised by badge at "
                f"ws://{badge_host}:{badge_port}/?token=<badge token>"
            )
        print(summary, flush=True)
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="Explicit serial port; never auto-scan attached boards")
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--supervise", action="store_true", help="Human-supervised bench movement")
    parser.add_argument("--badge-port", type=int, help="Let the badge's AUTO mode supervise")
    parser.add_argument("--badge-host", default="0.0.0.0", help="Interface the badge reaches")
    parser.add_argument(
        "--badge-token",
        default=os.environ.get("HTN_BADGE_TOKEN"),
        help="Shared secret in the badge URL (default: HTN_BADGE_TOKEN)",
    )
    args = parser.parse_args()
    if args.badge_port and args.supervise:
        parser.error("--supervise grants supervision permanently; use it or --badge-port")
    if args.badge_port and not args.badge_token:
        parser.error("--badge-port needs --badge-token or HTN_BADGE_TOKEN")
    device = serial.Serial(
        port=None, baudrate=115200, timeout=0.05, write_timeout=0.1, exclusive=True
    )
    # Keep normal line states: forcing both false reset this CH340/ESP32-S3.
    device.port = args.device
    device.open()
    try:
        asyncio.run(
            serve(
                device,
                args.port,
                args.supervise,
                args.badge_port,
                args.badge_host,
                args.badge_token,
            )
        )
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(serial.SerialException):
            device.write((json.dumps(STOP) + "\n").encode())
        device.close()


if __name__ == "__main__":
    main()
