"""Background WebSocket link to the robot base, speaking the dashboard's command packet.

The robot stops on its own if packets stop for 300 ms, so this link streams at 20 Hz for as
long as it runs: an idle packet (armed false) when no motion is requested, which never moves
anything and releases control, and the active command otherwise.
"""

import asyncio
import contextlib
import json
import threading
import time
from urllib.parse import quote

import websockets

RATE_HZ = 20


class RobotLink:
    def __init__(self, url: str, token: str):
        if not url.startswith("ws://"):
            raise ValueError("Robot URL must look like ws://host:81")
        self.url = f"{url.rstrip('/')}/?token={quote(token, safe='')}"
        self._lock = threading.Lock()
        self._sent = threading.Condition(self._lock)
        self._command: dict | None = None
        # Bumped on every set_command; tracks which command the last sent packet carried.
        self._generation = 0
        self._sent_generation = 0
        self._telemetry: dict = {}
        self._telemetry_at = 0.0
        self._connected = False
        self._seq = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="robot-link", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self.release()
        self._stop.set()
        self._thread.join(timeout=3)

    @property
    def connected(self) -> bool:
        return self._connected

    def set_command(self, command: dict | None) -> None:
        """`command` holds drive/arm/winch fields; None sends idle (disarmed) packets."""
        with self._lock:
            self._command = command
            self._generation += 1

    def release(self, timeout: float = 0.5) -> bool:
        """Switch to idle and wait until a disarmed packet is on the wire.

        Without this, a packet built just before the switch can still carry the old command.
        Returns False if no idle packet went out in time (e.g. the link is down; the robot's
        own 300 ms failsafe then stops it).
        """
        self.set_command(None)
        with self._sent:
            target = self._generation
            return self._sent.wait_for(lambda: self._sent_generation >= target, timeout)

    def telemetry(self) -> tuple[dict, float]:
        """Latest robot telemetry and its age in seconds (infinite before the first frame)."""
        with self._lock:
            age = time.monotonic() - self._telemetry_at if self._telemetry_at else float("inf")
            return dict(self._telemetry), age

    def _packet(self) -> tuple[str, int]:
        with self._lock:
            command, generation = self._command, self._generation
        self._seq += 1
        packet = {
            "type": "command",
            "source": "agent",
            "seq": self._seq,
            "t": int(time.time() * 1000),
            "estop": False,
            "armed": command is not None,
            "drive": {"left": 0.0, "right": 0.0},
            "winch": [0, 0, 0],
            "goal": None,
        }
        if command:
            packet.update(command)
        return json.dumps(packet), generation

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, open_timeout=5, ping_interval=None) as ws:
                    self._connected = True
                    receiver = asyncio.create_task(self._receive(ws))
                    try:
                        while not self._stop.is_set() and not receiver.done():
                            packet, generation = self._packet()
                            await ws.send(packet)
                            with self._sent:
                                self._sent_generation = generation
                                self._sent.notify_all()
                            await asyncio.sleep(1 / RATE_HZ)
                    finally:
                        receiver.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await receiver
            except (TimeoutError, OSError, websockets.WebSocketException):
                pass
            finally:
                self._connected = False
            if not self._stop.is_set():
                await asyncio.sleep(1)

    async def _receive(self, ws) -> None:
        async for message in ws:
            if not isinstance(message, str) or len(message) > 8192:
                continue
            try:
                frame = json.loads(message)
            except json.JSONDecodeError:
                continue
            if frame.get("type") == "telemetry":
                with self._lock:
                    self._telemetry = frame
                    self._telemetry_at = time.monotonic()
