"""Bounded server-side revisit proposals; Hydra applies joint pose/mesh corrections."""

import threading
from collections import deque
from queue import Empty

import numpy as np

from ...registration.rigid import difference
from ...registration.verification.partial import register
from .queue import LatestPerDevice


class LoopWorker:
    def __init__(self, features):
        self.features = features
        self.pending = LatestPerDevice()
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.history = {}
        self.last_attempt = {}
        self.accepted = deque(maxlen=8)
        self.generation = -1
        self.status = dict(attempts=0, proposed=0)
        self.thread = threading.Thread(target=self.run, daemon=True, name="room-revisits")
        self.thread.start()

    def offer(self, generation, frame):
        self.pending.replace((generation, frame, 0))

    def take(self, generation):
        with self.lock:
            ready = [edge for epoch, edge in self.accepted if epoch == generation]
            self.accepted.clear()
            return ready

    def run(self):
        try:
            while not self.stopping.is_set():
                try:
                    generation, frame, _ = self.pending.get(0.2)
                except Empty:
                    continue
                try:
                    self.process(generation, frame)
                except Exception as error:
                    with self.lock:
                        self.status["error"] = str(error)[:240]
        finally:
            self.features.close()

    def process(self, generation, frame):
        if generation < self.generation:
            return
        if generation != self.generation:
            self.history.clear()
            self.last_attempt.clear()
            self.features.clear()
            self.generation = generation
        device = (frame.provenance or {}).get("device_id", "single")
        history = self.history.setdefault(device, deque(maxlen=48))
        pose = np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
        if history:
            delta, angle = difference(pose, history[-1].pose)
            if delta < 0.10 and angle < 10:
                return
        history.append(self.features.extract(frame))
        now = frame.header.timestamp_s
        if len(history) < 12 or now - self.last_attempt.get(device, -100) < 10:
            return
        recent = list(history)[-5:]
        reference = [
            key
            for key in list(history)[:-6]
            if recent[0].frame.header.timestamp_s - key.frame.header.timestamp_s >= 10
        ]
        if len(reference) < 5:
            return
        self.last_attempt[device] = now
        result = register(recent, reference[:12], self.features)
        with self.lock:
            self.status["attempts"] += 1
        if result is None:
            return
        correction = np.array(result["room_from_local"]).reshape(4, 4, order="F")
        meters, degrees = difference(correction, np.eye(4))
        if meters > 0.75 or degrees > 8 or (meters < 0.015 and degrees < 0.5):
            return
        # Constraints link raw camera poses; the optimizer, not this worker, moves the map.
        current, old = recent[-1], reference[0]
        relative = np.linalg.inv(old.pose) @ correction @ current.pose
        edge = dict(
            from_timestamp_ns=round(current.frame.header.timestamp_s * 1e9),
            to_timestamp_ns=round(old.frame.header.timestamp_s * 1e9),
            to_T_from=relative.tolist(),
            verified_from_ns=[round(key.frame.header.timestamp_s * 1e9) for key in recent],
            verified_to_ns=[round(key.frame.header.timestamp_s * 1e9) for key in reference[:12]],
            evidence=result,
        )
        with self.lock:
            if len(self.accepted) < self.accepted.maxlen:
                self.accepted.append((generation, edge))
                self.status["proposed"] += 1
                self.status.pop("error", None)

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=20)
