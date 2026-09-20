"""WebSocket bridge for the agent app: ws://127.0.0.1:8793 <-> calibrated serial base.

  python agent_bridge.py /dev/cu.usbserial-10

One controller at a time. Every message is JSON:
  {"type":"command","armed":true,"estop":false,"drive":{"linear":0.3,"angular":0.0}}
  {"type":"command","armed":true,"estop":false,"drive":{"left":0.3,"right":0.3}}
  {"type":"command","armed":false,"estop":false}            stop
  {"type":"command","armed":false,"estop":true}             latched E-STOP (reset board to clear)
Values are -1..1 of the calibrated range; + linear is forward, + angular turns left (CCW).
Commands are a lease: repeat at >= 5 Hz or the firmware watchdog (300 ms) stops the base.
Firmware telemetry (motors, ir_raw, estop, ...) is pushed back at 20 Hz with "calibration" added.
"""

import argparse
import asyncio
import json
import math

import websockets

from base import Base

LIMIT = 1.0


def wheels(message, limit):
    value = json.loads(message)
    if not isinstance(value, dict) or value.get("type") != "command":
        raise ValueError("Expected command")
    if type(value.get("armed")) is not bool or type(value.get("estop")) is not bool:
        raise ValueError("Explicit armed/estop booleans required")
    if value["estop"]:
        return "estop"
    if not value["armed"]:
        return None
    drive = value.get("drive") or {}
    if "linear" in drive or "angular" in drive:
        linear, angular = drive.get("linear", 0), drive.get("angular", 0)
        pair = (linear - angular, linear + angular)
    else:
        pair = (drive.get("left"), drive.get("right"))
    if not all(type(v) in (int, float) and math.isfinite(v) for v in pair):
        raise ValueError("Finite drive values required")
    peak = max(1.0, *(abs(v) / limit for v in pair))
    return tuple(max(-limit, min(limit, v / peak)) for v in pair)


class Bridge:
    def __init__(self, base, limit):
        self.base, self.limit, self.active = base, limit, False

    async def telemetry(self, ws):
        while True:
            state = dict(self.base.telemetry or {}, calibration=self.base.cal)
            await ws.send(json.dumps(state))
            await asyncio.sleep(0.05)

    async def client(self, ws):
        if self.active:
            await ws.close(code=1008, reason="Controller already connected")
            return
        self.active = True
        feed = asyncio.create_task(self.telemetry(ws))
        try:
            async for message in ws:
                try:
                    target = wheels(message, self.limit)
                except (ValueError, TypeError, AttributeError) as error:
                    self.base.stop()
                    await ws.close(code=1008, reason=str(error)[:100])
                    break
                if target == "estop":
                    self.base.estop()
                elif target is None:
                    self.base.stop()
                else:
                    self.base.drive(*target)
        except websockets.ConnectionClosed:
            pass
        finally:
            feed.cancel()
            self.base.stop()
            self.active = False


async def serve(base, host, port, limit):
    async with websockets.serve(Bridge(base, limit).client, host, port, max_size=2048):
        print(f"Base bridge ws://{host}:{port} (limit {limit})", flush=True)
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="Explicit serial port")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--ws-port", type=int, default=8793)
    parser.add_argument("--limit", type=float, default=0.5, help="Cap on |wheel| commands, 0..1")
    args = parser.parse_args()
    with Base(args.port) as base:
        try:
            asyncio.run(serve(base, args.host, args.ws_port, min(args.limit, LIMIT)))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
