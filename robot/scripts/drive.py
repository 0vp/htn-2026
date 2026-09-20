"""One app for driving the base: arrow keys here, plus a WebSocket for the iOS/agent app.

  python drive.py /dev/cu.usbserial-10                      # keyboard + ws://127.0.0.1:8793
  python drive.py PORT --host 0.0.0.0 --token SECRET        # let a phone on the LAN connect:
                                                            # ws://<laptop-ip>:8793/?token=SECRET
Keys: arrows drive while held | space stop | [ ] trim left/right (saved) | - = speed | q quit.
The keyboard always wins over the app; space also drops the app's current command.

App messages (JSON, one controller at a time, repeat at >= 5 Hz; values -1..1):
  {"type":"command","armed":true,"estop":false,"drive":{"linear":0.3,"angular":0.0}}
  {"type":"command","armed":true,"estop":false,"drive":{"left":0.3,"right":0.3}}
  {"type":"command","armed":false,"estop":false}     stop
  {"type":"command","armed":false,"estop":true}      latched E-STOP (reset the board to clear)
+ linear is forward, + angular turns left. Telemetry is pushed back at 20 Hz.
"""

import argparse
import asyncio
import curses
import hmac
import json
import math
import time
from urllib.parse import parse_qs, urlsplit

import websockets

from base import CALIBRATION, Base

KEY_HOLD_S = 0.6  # Covers the OS delay between the first key press and its repeats.
APP_LEASE_S = 0.3
KEYS = {
    curses.KEY_UP: (1, 1),
    curses.KEY_DOWN: (-1, -1),
    curses.KEY_LEFT: (-1, 1),
    curses.KEY_RIGHT: (1, -1),
}


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


class App:
    def __init__(self, base, args):
        self.base, self.args = base, args
        self.speed = args.speed
        self.key_motion, self.key_at = (0, 0), 0.0
        self.app_motion, self.app_at = None, 0.0
        self.connected, self.source, self.done = False, "idle", False

    # --- WebSocket side ---
    def allowed(self, ws):
        if not self.args.token:
            return True
        given = (parse_qs(urlsplit(ws.request.path).query).get("token") or [""])[0]
        return hmac.compare_digest(given.encode(), self.args.token.encode())

    async def client(self, ws):
        if not self.allowed(ws) or self.connected:
            await ws.close(
                code=1008, reason="Token required or controller already connected"
            )
            return
        self.connected = True
        feed = asyncio.create_task(self.feed(ws))
        try:
            async for message in ws:
                try:
                    target = wheels(message, self.args.limit)
                except (ValueError, TypeError, AttributeError) as error:
                    await ws.close(code=1008, reason=str(error)[:100])
                    break
                if target == "estop":
                    self.base.estop()
                    target = None
                self.app_motion, self.app_at = target, time.monotonic()
        except websockets.ConnectionClosed:
            pass
        finally:
            feed.cancel()
            self.app_motion, self.connected = None, False

    def report(self):
        """Firmware telemetry plus the fields the backend motion skills gate on."""
        state = dict(
            self.base.telemetry or {}, source=self.source, calibration=self.base.cal
        )
        owner = dict(keyboard="human", app="agent").get(self.source, "none")
        # Running this app is the act of supervising: a person is at the keyboard with space/q.
        state["control"] = dict(
            owner=owner,
            supervised=bool(state.get("supervised")),
            estop=state.get("estop", True),
        )
        state["motor_duty"] = max(
            (abs(v) for v in (state.get("motors") or {}).values()), default=None
        )
        state["capabilities"] = dict(drive_base=True)
        return state

    async def feed(self, ws):
        while True:
            state = self.report()
            await ws.send(json.dumps(state))
            await asyncio.sleep(0.05)

    # --- Keyboard side ---
    def trim(self, step):
        """+ step slows the right wheel (robot was veering left); - step slows the left."""
        cal = self.base.cal
        ratio = max(0.5, min(2.0, cal["right_gain"] / cal["left_gain"] - step))
        cal["left_gain"], cal["right_gain"] = (
            (round(1 / ratio, 3), 1.0) if ratio > 1 else (1.0, round(ratio, 3))
        )
        CALIBRATION.write_text(json.dumps(cal, indent=2) + "\n")

    def keys(self, screen):
        key = screen.getch()
        while (extra := screen.getch()) != -1:
            key = extra
        now = time.monotonic()
        if key in (ord("q"), 27):
            self.done = True
        elif key == ord(" "):
            self.key_motion, self.app_motion = (0, 0), None
        elif key in KEYS:
            self.key_motion, self.key_at = tuple(v * self.speed for v in KEYS[key]), now
        elif key in (ord("["), ord("]")):
            self.trim(0.02 if key == ord("]") else -0.02)  # ] = steer more to the right
        elif key in (ord("-"), ord("=")):
            self.speed = max(
                0.1, min(1.0, self.speed + (0.05 if key == ord("=") else -0.05))
            )

    def tick(self):
        now = time.monotonic()
        if now - self.key_at <= KEY_HOLD_S and self.key_motion != (0, 0):
            self.source, motion = "keyboard", self.key_motion
        elif self.app_motion and now - self.app_at <= APP_LEASE_S:
            self.source, motion = "app", self.app_motion
        else:
            self.source, motion = "idle", None
        if motion:
            self.base.drive(*motion)
        else:
            self.base.stop()

    def draw(self, screen):
        state, cal = self.base.telemetry or {}, self.base.cal
        where = f"ws://{self.args.host}:{self.args.ws_port}"
        rows = [
            "arrows drive | space stop | [ ] trim | - = speed | q quit",
            f"source {self.source:8} speed {self.speed:.2f}  app {'connected' if self.connected else 'waiting'} {where}",
            f"trim L{cal['left_gain']:.3f} R{cal['right_gain']:.3f}  motors {state.get('motors')}",
            f"ir {state.get('ir_raw')}  estop {state.get('estop')}",
        ]
        screen.erase()
        for index, row in enumerate(rows):
            screen.addnstr(index, 0, row, curses.COLS - 1)
        screen.refresh()

    async def run(self, screen):
        curses.curs_set(0)
        screen.nodelay(True)
        async with websockets.serve(
            self.client, self.args.host, self.args.ws_port, max_size=2048
        ):
            while not self.done:
                self.keys(screen)
                self.tick()
                self.draw(screen)
                await asyncio.sleep(0.04)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="Explicit serial port")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--ws-port", type=int, default=8793)
    parser.add_argument("--token", help="Required from app clients as ?token=...")
    parser.add_argument("--speed", type=float, default=0.2, help="Keyboard level, 0..1")
    parser.add_argument(
        "--limit", type=float, default=0.6, help="Cap on app wheel commands"
    )
    args = parser.parse_args()
    if args.host != "127.0.0.1" and not args.token:
        parser.error("--token is required when listening beyond loopback")
    with Base(args.port) as base:
        curses.wrapper(lambda screen: asyncio.run(App(base, args).run(screen)))


if __name__ == "__main__":
    main()
