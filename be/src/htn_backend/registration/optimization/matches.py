"""Bounded identity cache for immutable extracted keyframes, never frame IDs alone."""

from collections import OrderedDict
from threading import Lock
from weakref import ref


class PairMatches:
    def __init__(self, match, capacity: int = 576):
        if capacity < 1:
            raise ValueError("match cache capacity must be positive")
        self.match = match
        self.capacity = capacity
        self.entries = OrderedDict()
        self.lock = Lock()
        self.generation = 0
        self.hits = 0
        self.misses = 0

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.generation += 1

    def prime(self, pairs, compute_many):
        with self.lock:
            generation = self.generation
            missing = {}
            for source, target in pairs:
                key = id(source), id(target)
                entry = self.entries.get(key)
                if entry is None or entry[0]() is not source or entry[1]() is not target:
                    missing[key] = source, target
            self.misses += len(missing)
        if not missing:
            return
        values = compute_many(list(missing.values()))
        if len(values) != len(missing):
            raise ValueError("match batch result count mismatch")
        for (source, target), result in zip(missing.values(), values, strict=True):
            self._store(source, target, result, generation)

    def __call__(self, source, target):
        key = (id(source), id(target))
        with self.lock:
            generation = self.generation
            entry = self.entries.get(key)
            if entry is not None and entry[0]() is source and entry[1]() is target:
                self.entries.move_to_end(key)
                self.hits += 1
                return entry[2]
            self.misses += 1
        result = self.match(source, target)
        self._store(source, target, result, generation)
        return result

    def _store(self, source, target, result, generation):
        key = id(source), id(target)
        for array in result:
            array.flags.writeable = False
        with self.lock:
            if generation == self.generation:
                # Identity is verified through weak refs; evicted views are not kept alive.
                self.entries[key] = (ref(source), ref(target), result)
                self.entries.move_to_end(key)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)


def prefetch(match, source, target):
    prepare = getattr(match, "prefetch", None)
    if prepare is not None:
        prepare([(left, right) for left in source for right in target])
