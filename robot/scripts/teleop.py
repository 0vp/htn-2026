"""Arrow-key driving. Hold an arrow to move; release to stop. Space = stop, q = quit.

  python teleop.py /dev/cu.usbserial-10 --speed 0.4

Terminals only report key repeats, so motion continues for HOLD_S after the last key event.
"""

import argparse
import curses
import time

from base import Base

HOLD_S = 0.6  # Covers the OS delay between the first key press and its repeats.
KEYS = {
    curses.KEY_UP: (1, 1),
    curses.KEY_DOWN: (-1, -1),
    curses.KEY_LEFT: (-1, 1),
    curses.KEY_RIGHT: (1, -1),
}


def loop(screen, base, speed, turn):
    curses.curs_set(0)
    screen.nodelay(True)
    motion, pressed = (0, 0), 0.0
    while True:
        key = screen.getch()
        while (extra := screen.getch()) != -1:
            key = extra
        if key in (ord("q"), 27):
            return
        if key == ord(" "):
            motion = (0, 0)
        elif key in KEYS:
            scale = speed if key in (curses.KEY_UP, curses.KEY_DOWN) else turn
            motion, pressed = tuple(v * scale for v in KEYS[key]), time.monotonic()
        if time.monotonic() - pressed > HOLD_S:
            motion = (0, 0)
        if motion == (0, 0):
            base.stop()
        else:
            base.drive(*motion)
        state = base.telemetry or {}
        screen.erase()
        screen.addstr(0, 0, "arrows drive | space stop | q quit")
        screen.addstr(1, 0, f"command {motion}  motors {state.get('motors')}  ir {state.get('ir_raw')}")
        screen.refresh()
        time.sleep(0.04)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--speed", type=float, default=0.4, help="0..1 of the calibrated range")
    parser.add_argument("--turn", type=float, default=0.4)
    args = parser.parse_args()
    with Base(args.port) as base:
        curses.wrapper(loop, base, min(args.speed, 1.0), min(args.turn, 1.0))


if __name__ == "__main__":
    main()
