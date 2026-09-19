"""Separate observation time from expensive graph publication under replay/load."""

import time


class GraphCadence:
    interval_s = 0.4

    def __init__(self):
        self.capture_ns = None
        self.finished_s = None

    def due(self, capture_ns, now):
        if self.capture_ns is None:
            return True
        return (
            capture_ns - self.capture_ns >= self.interval_s * 1e9
            and now - self.finished_s >= self.interval_s
        )

    def published(self, capture_ns, now):
        self.capture_ns, self.finished_s = capture_ns, now


class CadencedMapper:
    """Integrate every observation once; publish accumulated updates on a bounded cadence.

    The native partial-update/flush bridge retains original timestamps and avoids
    reintegrating depth during flush. Idle and loop-closure flushes remain immediate.
    """

    def __init__(self, mapper, clock=time.monotonic):
        self.mapper, self.clock = mapper, clock
        self.cadence = GraphCadence()
        self.latest = None

    def __getattr__(self, name):
        return getattr(self.mapper, name)

    def step(self, stamp, *args):
        self.latest = stamp
        updated = self.mapper.step(stamp, *args)
        if (
            not updated
            and self.mapper.last_input_accepted
            and self.cadence.due(stamp, self.clock())
        ):
            updated = self.mapper.flush()
        if updated:
            self.cadence.published(stamp, self.clock())
        return updated

    def flush(self, force=False):
        updated = self.mapper.flush(force)
        if updated:
            self.cadence.published(self.latest, self.clock())
        return updated
