"""Serial link to the robot/src firmware, with calibration applied on the host.

Logical commands are (left, right) in -1..1 where + means the robot's forward. Calibration maps
them to raw driver duty: sign flip per wheel, per-wheel gain (trim) and a minimum moving duty.
"""

import json
import threading
import time
from pathlib import Path

import serial

DRIVETRAIN = "bts7960_diff_v2"
CALIBRATION = Path(__file__).with_name("calibration.json")
DEFAULTS = dict(
    left_sign=1, right_sign=1, left_gain=1.0, right_gain=1.0, left_min=0.0, right_min=0.0,
    swap=False,  # True when the driver wired as "left" turned out to be the right wheel.
)


def load_calibration(path=CALIBRATION):
    values = dict(DEFAULTS)
    if Path(path).exists():
        values.update(json.loads(Path(path).read_text()))
    return values


class Base:
    def __init__(self, port, calibration=None, raw=False):
        self.cal = dict(DEFAULTS) if raw else (calibration or load_calibration())
        self.telemetry, self.heard, self.max_duty = None, 0.0, 0.25
        self.port, self.lost = port, False
        self.device = serial.Serial(port, 115200, timeout=0.05, write_timeout=0.2)
        self.alive = True
        threading.Thread(target=self._read, daemon=True).start()
        deadline = time.monotonic() + 5  # Opening the CH340 port can reset the board.
        while self.telemetry is None:
            if time.monotonic() > deadline:
                raise TimeoutError(f"No {DRIVETRAIN} telemetry on {port}")
            time.sleep(0.05)
        self.max_duty = float(self.telemetry["max_duty"])
        self.stop()
        self._send(dict(type="supervise", enabled=True))

    def _read(self):
        while self.alive:
            try:
                value = json.loads(self.device.readline())
            except (ValueError, UnicodeError):
                continue
            except (serial.SerialException, OSError, TypeError):
                self.lost = True
                return
            if isinstance(value, dict) and value.get("drivetrain") == DRIVETRAIN:
                self.telemetry, self.heard = value, time.monotonic()

    def _send(self, value):
        try:
            self.device.write((json.dumps(value) + "\n").encode())
        except (serial.SerialException, OSError):
            self.lost = True  # Unplugged or reset; the firmware watchdog stops the motors.

    def reconnect(self) -> bool:
        """Reopen the serial port after an unplug; True once telemetry flows again."""
        try:
            self.device.close()
        except (serial.SerialException, OSError):
            pass
        try:
            self.device = serial.Serial(self.port, 115200, timeout=0.05, write_timeout=0.2)
        except (serial.SerialException, OSError):
            return False
        self.lost, self.telemetry = False, None
        threading.Thread(target=self._read, daemon=True).start()
        self._send(dict(type="supervise", enabled=True))
        return True

    def _raw(self, value, side):
        if abs(value) < 1e-3:
            return 0.0
        low = self.cal[f"{side}_min"]
        duty = low + (self.max_duty - low) * min(abs(value), 1.0) * self.cal[f"{side}_gain"]
        duty = min(duty, self.max_duty)
        return round(duty * self.cal[f"{side}_sign"] * (1 if value > 0 else -1), 4)

    def drive(self, left, right):
        """Must be repeated at least every 300 ms or the firmware watchdog stops the base."""
        if self.lost or time.monotonic() - self.heard > 0.5:
            self.lost = True
            return
        if self.cal["swap"]:
            left, right = right, left
        motors = dict(left=self._raw(left, "left"), right=self._raw(right, "right"))
        self._send(dict(type="command", armed=True, estop=False, motors=motors))

    def run(self, left, right, seconds):
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                self.drive(left, right)
                time.sleep(0.05)
        finally:
            self.stop()

    def stop(self):
        self._send(dict(type="command", armed=False, estop=False))

    def estop(self):
        self._send(dict(type="command", armed=False, estop=True))

    def close(self):
        try:
            self.stop()
            self._send(dict(type="supervise", enabled=False))
        finally:
            self.alive = False
            self.device.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
