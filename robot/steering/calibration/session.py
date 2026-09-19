"""Keep a single serial connection for individually requested, bounded bench pulses.

Each stdin line is JSON with duty, steering_deg and seconds. No pulse is queued or
replayed on reconnect: a transport error ends this session. The motor is disarmed
between requests. Run via `uv run --project be python .../session.py PORT`.
"""

import argparse
import contextlib
import json
import sys

import serial
from pulse import STOP, pulse


def run(device, lines, output):
    try:
        for line in lines:
            try:
                value = json.loads(line)
                result = pulse(
                    device, value["duty"], value["steering_deg"], value["seconds"]
                )
            except (KeyError, TypeError, ValueError, RuntimeError) as error:
                result = {"error": str(error), "reported_stop": False}
            print(json.dumps(result, allow_nan=False), file=output, flush=True)
            if not result.get("reported_stop"):
                break
    finally:
        for value in (STOP, {"type": "supervise", "enabled": False}):
            with contextlib.suppress(serial.SerialException, OSError):
                device.write((json.dumps(value) + "\n").encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    args = parser.parse_args()
    # Default asserted DTR/RTS tested on this board; do not toggle between pulses.
    with serial.Serial(args.port, 115200, timeout=0.04, write_timeout=0.2) as device:
        run(device, sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
