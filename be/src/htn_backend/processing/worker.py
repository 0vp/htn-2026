"""Single durable journal consumer, supervised independently of HTTP uploads."""

import fcntl
import logging
import os
import signal
import threading
import time
from collections import OrderedDict
from pathlib import Path

from ..inference.client import Detector
from ..storage.database import Store
from ..storage.retention import cleanup
from .room import RoomProcessor
from .state import ProcessingState

LOG = logging.getLogger(__name__)


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    root = Path(os.environ.get("HTN_DATA_DIR", "data"))
    root.mkdir(parents=True, exist_ok=True)
    with (root / "processing.lock").open("w") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store = Store(root)
        state = ProcessingState(store)
        detector = Detector()
        stopping = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stopping.set())
        signal.signal(signal.SIGINT, lambda *_: stopping.set())
        rooms, cooldown, completed = OrderedDict(), {}, {}
        last_cleanup = 0.0

        def heartbeat():
            while not stopping.wait(5):
                state.touch()

        pulse = threading.Thread(target=heartbeat, daemon=True)
        pulse.start()
        state.heartbeat("running")
        try:
            while not stopping.is_set():
                if time.monotonic() - last_cleanup > 30:
                    for _ in range(8):
                        if cleanup(store)["frames_cleaned"] < 128:
                            break
                    last_cleanup = time.monotonic()
                if not detector.ready():
                    state.heartbeat("waiting_for_gpu")
                    stopping.wait(2)
                    continue
                state.heartbeat("running")
                worked = False
                for room in reversed(store.rooms()):
                    code = room["room_id"]
                    if not room["frames_stored"] or cooldown.get(code, 0) > time.monotonic():
                        continue
                    if completed.get(code) == room["frames_stored"] and code not in rooms:
                        continue
                    try:
                        if code in rooms and rooms[code].reset_count != room["reset_count"]:
                            # The room was wiped; nothing held in memory describes it any more.
                            rooms.pop(code).close()
                            completed.pop(code, None)
                        if code not in rooms:
                            if len(rooms) >= 2:
                                idle = next((r for r in rooms if r in completed), None)
                                if idle is None:
                                    continue
                                rooms.pop(idle).close(checkpoint=True)
                            rooms[code] = RoomProcessor(state, code, detector)
                            rooms[code].reset_count = room["reset_count"]
                        processor = rooms[code]
                        rooms.move_to_end(code)
                        if completed.get(code) != room["frames_stored"]:
                            completed.pop(code, None)
                        changed = processor.step()
                        worked |= changed
                        state.error(code, None)
                        if not changed:
                            completed[code] = room["frames_stored"]
                    except Exception as error:
                        state.error(code, str(error))
                        LOG.exception("Room processing failed: %s", code)
                        state.heartbeat(
                            "retrying", f"Room {code}: processing failed; captures retained"
                        )
                        cooldown[code] = time.monotonic() + 30
                        if code in rooms:
                            rooms.pop(code).close()
                    if stopping.is_set():
                        break
                if not worked:
                    stopping.wait(0.25)
        finally:
            stopping.set()
            pulse.join(timeout=6)
            for processor in rooms.values():
                processor.close(checkpoint=True)
            detector.close()
            state.heartbeat("stopped")
            store.close()


if __name__ == "__main__":
    run()
