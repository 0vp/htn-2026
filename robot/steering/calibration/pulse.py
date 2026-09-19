"""One short supervised calibration pulse; leaves drive stopped and supervision off.

Use only with a current camera view, clear wheels and slack tether. This does not
perform autonomous calibration, obstacle detection or estimate physical distance.
"""

import argparse
import json
import math
import time

import serial

STOP = {"type": "command", "armed": False, "estop": False}


def pulse(device, duty, steering, seconds):
    if not all(math.isfinite(x) for x in (duty, steering, seconds)):
        raise ValueError("Finite pulse parameters required")
    if abs(duty) > 0.15 or abs(steering) > 10 or not 0 < seconds <= 0.3:
        raise ValueError("Calibration pulse exceeds 15% duty, 10 degrees or 300ms")
    samples = []

    def send(value):
        device.write((json.dumps(value, allow_nan=False) + "\n").encode())

    def read():
        try:
            value = json.loads(device.readline())
        except (ValueError, UnicodeError):
            return None
        if isinstance(value, dict) and value.get("drivetrain") == "single_steer_v1":
            samples.append(
                dict(elapsed_s=round(time.monotonic() - started, 4), **value)
            )
            return value
        return None

    started = time.monotonic()
    try:
        send(STOP)
        send({"type": "supervise", "enabled": False})
        deadline = started + 2
        while time.monotonic() < deadline:
            state = read()
            if state and state.get("motor_duty") == 0:
                break
        else:
            raise RuntimeError("Stopped steering firmware not verified")
        if state.get("control", {}).get("estop", True):
            raise RuntimeError("Emergency stop is latched")
        send({"type": "supervise", "enabled": True})
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            send(
                {
                    "type": "command",
                    "armed": True,
                    "estop": False,
                    "drive": {"duty": duty, "steering_deg": steering},
                }
            )
            read()
            time.sleep(0.01)
        send(STOP)
        send({"type": "supervise", "enabled": False})
        deadline = time.monotonic() + 1
        stopped = False
        while time.monotonic() < deadline:
            state = read()
            if (
                state
                and state.get("motor_duty") == 0
                and not state["control"]["supervised"]
            ):
                stopped = True
                break
        return {
            "command": {"duty": duty, "steering_deg": steering, "seconds": seconds},
            "reported_stop": stopped,
            "physical_stop_verified": False,
            "samples": samples,
        }
    finally:
        send(STOP)
        send({"type": "supervise", "enabled": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--duty", type=float, required=True)
    parser.add_argument("--steering", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=0.2)
    args = parser.parse_args()
    device = serial.Serial(port=None, baudrate=115200, timeout=0.04, write_timeout=0.1)
    device.dtr = device.rts = False
    device.port = args.port
    device.open()
    try:
        print(
            json.dumps(pulse(device, args.duty, args.steering, args.seconds), indent=2)
        )
    finally:
        device.close()


if __name__ == "__main__":
    main()
