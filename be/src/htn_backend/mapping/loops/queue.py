"""Keep one pending frame per phone, so one fast sender cannot evict another."""

import threading
import time
from collections import OrderedDict
from queue import Empty


class LatestPerDevice:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.items = OrderedDict()
        self.generation = -1

    def replace(self, item: tuple) -> bool:
        generation, frame, _ = item
        key = (frame.provenance or {}).get("device_id", "single")
        with self.condition:
            if generation < self.generation:
                return True
            if generation != self.generation:
                self.items.clear()
                self.generation = generation
            dropped = self.items.pop(key, None) is not None
            if len(self.items) >= 16:
                raise ValueError("pending device limit reached")
            # Move a replaced observation to the tail to preserve global receipt order.
            self.items[key] = item
            self.condition.notify()
            return dropped

    def get(self, timeout: float) -> tuple:
        deadline = time.monotonic() + timeout
        with self.condition:
            while not self.items:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Empty
                self.condition.wait(remaining)
            return self.items.popitem(last=False)[1]

    def qsize(self) -> int:
        with self.condition:
            return len(self.items)
