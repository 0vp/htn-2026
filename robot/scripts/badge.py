"""The badge as a wired app client: its command lines arrive over USB instead of a WebSocket.

The badge writes one `{"type":"command",...}` line per packet to its own USB CDC port at 20 Hz
and reads telemetry lines back on the same port. Everything else on that port is console text
(`help`, `status`), so anything that is not a JSON object is ignored rather than treated as noise.

Only one program can hold the port, so `pio device monitor` has to be closed while this runs.
"""

import json
import threading
import time
from collections import deque

import serial


class Badge:
    """Reader thread plus a queue of pending command lines, mirroring base.Base's pattern."""

    def __init__(self, port: str):
        self.port = port
        self.device = serial.Serial(port, 115200, timeout=0.05, write_timeout=0.2)
        self.pending: deque[str] = deque(maxlen=8)  # Only the newest packets matter.
        self.lost = False
        self.heard = 0.0
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        while self.alive:
            try:
                raw = self.device.readline()
            except (serial.SerialException, OSError):
                self.lost = True
                return
            if not raw.startswith(b"{"):
                continue  # Console output, not a packet.
            self.pending.append(raw.decode("utf-8", "replace"))
            self.heard = time.monotonic()

    def poll(self) -> list[str]:
        """Command lines received since the last call, oldest first."""
        out = []
        while self.pending:
            out.append(self.pending.popleft())
        return out

    def send(self, state: dict) -> None:
        """Push one telemetry frame; the badge treats silence over 1 s as the link being gone."""
        try:
            self.device.write((json.dumps(state) + "\n").encode())
        except (serial.SerialException, OSError):
            self.lost = True

    def close(self) -> None:
        self.alive = False
        try:
            self.device.close()
        except (serial.SerialException, OSError):
            pass
