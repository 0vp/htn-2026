"""Replayable room fusion; inference overlaps while native mutations remain ordered."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np

from ..capture.codec import decode
from ..mapping.hydra.client import HydraClient
from ..mapping.hydra.snapshot import snapshot
from ..mapping.loops.anchors import NativeAnchors
from ..mapping.loops.poses import corrected_frame
from ..mapping.loops.worker import LoopWorker
from ..mapping.objects.confirmation import ObjectConfirmation
from ..mapping.objects.lifecycle import ObjectLifecycle
from ..mapping.objects.orientation import AxialOrientation
from ..mapping.objects.surfaces import samples
from .alignment import Alignment
from .mesh import glb


class RoomProcessor:
    def __init__(self, state, room_id, detector, mapper_factory=HydraClient):
        self.state, self.room_id, self.detector = state, room_id, detector
        self.mapper_factory = mapper_factory
        self.alignment = Alignment(state, room_id, detector.features)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="inference")
        self.last_work = time.monotonic()
        factory = getattr(detector, "loop_features", None)
        self.loops = LoopWorker(factory()) if factory else None
        self.generation = 0
        self.reset()

    def reset(self):
        if getattr(self, "mapper", None) is not None:
            self.mapper.close()
        self.mapper = self.mapper_factory()
        self.generation += 1
        self.anchors = NativeAnchors()
        self.submitted_loops = 0
        self.cursor = 0
        self.count = 0
        self.unpublished = []
        current = self.state.status(self.room_id)["map"]
        self.publish_after = current.get("through_sequence", 0) if current else 0
        self.confirmation = ObjectConfirmation()
        self.lifecycle = ObjectLifecycle()
        self.orientation = AxialOrientation()

    def step(self) -> bool:
        rows = self.state.store.frames(self.room_id, self.cursor, 4)
        if not rows:
            edges = self.anchors.resolve(self.loops.take(self.generation)) if self.loops else []
            if not edges or not self.count:
                return False
            result = self.mapper.flush(edges)
            self.submitted_loops += len(edges)
            self.publish(result, [], self.cursor, time.perf_counter())
            return True
        self.last_work = time.monotonic()
        ready = []
        for row in rows:
            frame = decode(self.state.store.payload(self.room_id, row["sequence"]))
            if frame.header.tracking != "normal" or not frame.rgb_jpeg:
                self.state.mark(
                    row["sequence"], "skipped_tracking", "Normal tracking and RGB required"
                )
                self.cursor = row["sequence"]
                continue
            if self.alignment.observe(row, frame):
                # A new verified origin changes the room graph. Rebuild from the journal,
                # including all previously deferred captures; never silently omit them.
                self.reset()
                return True
            transform = self.alignment.transform(row)
            if transform is None:
                self.state.mark(row["sequence"], "awaiting_alignment")
                self.cursor = row["sequence"]
                continue
            pose = transform @ np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
            # Native integration time is ordered server sequence, NOT phone wall time.
            header = frame.header.model_copy(
                update={
                    "timestamp_s": row["sequence"] * 0.2,
                    "camera_to_world": tuple(pose.flatten(order="F")),
                }
            )
            observed = replace(
                frame,
                header=header,
                provenance={
                    "device_id": row["device_id"],
                    "capture_timestamp_s": frame.header.timestamp_s,
                },
            )
            ready.append((row, observed, self.pool.submit(self.detector, observed)))
        if not ready:
            return True
        began = time.perf_counter()
        observations = []
        for _row, frame, future in ready:
            detections = future.result(timeout=25)
            self.anchors.observe(frame)
            edges = self.anchors.resolve(self.loops.take(self.generation)) if self.loops else []
            result = (
                self.mapper.integrate(frame, detections, edges)
                if edges
                else self.mapper.integrate(frame, detections)
            )
            self.submitted_loops += len(edges)
            if self.loops:
                self.loops.offer(self.generation, frame)
            self.count += 1
            observations.append((frame, detections))
        if not result.get("updated", True):
            result = self.mapper.flush()
        if result is None or not result.get("updated", True):
            raise RuntimeError("Native graph did not publish after flush")
        self.unpublished.extend(row["sequence"] for row, _, _ in ready)
        self.cursor = rows[-1]["sequence"]
        self.publish(result, observations, self.cursor, began)
        return True

    def publish(self, result, observations, through_sequence, began):
        self.anchors.update(result.get("agents", []))
        mesh, objects = snapshot(result, self.count, self.count)
        surfaces = samples(result)
        confirmed = self.confirmation.retained(objects)
        for frame, detections in observations:
            if self.submitted_loops:
                frame = corrected_frame(frame, result.get("agents", []))
            if frame is not None:
                confirmed = self.confirmation.update(frame, detections, objects, surfaces)
                confirmed = self.lifecycle.update(frame, confirmed, surfaces)
        confirmed = self.orientation.update(confirmed)
        if self.cursor < self.publish_after:
            return
        self.state.publish(
            self.room_id,
            glb(mesh[0], mesh[1]),
            confirmed,
            {
                "backend": "hydra",
                "coordinate_system": "right_handed_y_up_meters",
                "integrated_frames": self.count,
                "through_sequence": through_sequence,
                "vertices": len(mesh[0]),
                "triangles": len(mesh[1]),
                "batch_ms": (time.perf_counter() - began) * 1000,
                "object_events": list(self.lifecycle.events),
                "loop_constraints": self.submitted_loops,
                "loop_detection": dict(self.loops.status) if self.loops else {},
                "replaying": False,
            },
            self.unpublished,
            {
                o["object_id"]: self.confirmation.tracks[o["object_id"]]["evidence"]
                for o in confirmed
                if self.confirmation.tracks[o["object_id"]].get("evidence")
            },
        )
        self.unpublished.clear()

    def close(self):
        if self.loops:
            self.loops.close()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.mapper.close()
