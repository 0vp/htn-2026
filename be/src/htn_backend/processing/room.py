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
from ..storage.retention import cleanup
from .alignment import Alignment
from .atlas.store import Atlas
from .mesh import glb


class RoomProcessor:
    segment_frames = 256
    segment_radius_m = 8.0

    def __init__(self, state, room_id, detector, mapper_factory=HydraClient):
        self.state, self.room_id, self.detector = state, room_id, detector
        self.mapper_factory = mapper_factory
        self.atlas = Atlas(state.store, room_id)
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
        self.segment_sequences = []
        self.last_composed = None
        self.origin = None
        current = self.state.status(self.room_id)["map"]
        self.publish_after = current.get("through_sequence", 0) if current else 0
        self.confirmation = ObjectConfirmation()
        self.lifecycle = ObjectLifecycle()
        self.orientation = AxialOrientation()

    def step(self) -> bool:
        rows = self.state.store.active_frames(self.room_id, self.cursor, 4)
        if not rows:
            edges = self.anchors.resolve(self.loops.take(self.generation)) if self.loops else []
            if not edges or not self.count:
                # Seal idle captures too, so short scans do not retain raw data forever.
                if self.count and time.monotonic() - self.last_work > 30:
                    self.seal()
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
            if self.origin is None:
                self.origin = pose[:3, 3].copy()
            boundary = (
                self.count + len(ready) >= self.segment_frames
                or np.linalg.norm(pose[:3, 3] - self.origin) > self.segment_radius_m
            )
            if boundary:
                if ready:
                    rows = rows[: rows.index(row)]
                    break
                if self.count:
                    self.seal()
                    return True
            pose[:3, 3] -= self.origin
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
                    "received_at": row["received_at"],
                    "sequence": row["sequence"],
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
        self.segment_sequences.extend(row["sequence"] for row, _, _ in ready)
        self.cursor = rows[-1]["sequence"]
        self.publish(result, observations, self.cursor, began)
        return True

    def publish(self, result, observations, through_sequence, began):
        self.anchors.update(result.get("agents", []))
        mesh, objects = snapshot(result, self.count, self.count)
        surfaces = samples(result)
        if "instance_objects" in result:
            objects = result["instance_objects"]
            surfaces = result["instance_surfaces"]
        confirmed = self.confirmation.retained(objects)
        for frame, detections in observations:
            if self.submitted_loops:
                frame = corrected_frame(frame, result.get("agents", []))
            if frame is not None:
                confirmed = self.confirmation.update(frame, detections, objects, surfaces)
                confirmed = self.lifecycle.update(frame, confirmed, surfaces)
        confirmed = self.orientation.update(confirmed)
        # Native geometry is local to a bounded segment; publication is always in room space.
        vertices = mesh[0] + self.origin
        for obj in confirmed:
            obj["center_m"] = (np.array(obj["center_m"]) + self.origin).tolist()
        evidence = {
            o["object_id"]: self.confirmation.tracks[o["object_id"]]["evidence"]
            for o in confirmed
            if self.confirmation.tracks[o["object_id"]].get("evidence")
        }
        vertices, faces, objects, evidence, groups = self.atlas.compose(
            vertices, mesh[1], confirmed, evidence
        )
        self.last_composed = groups, objects, evidence
        if (
            self.cursor < self.publish_after
            and self.atlas.frames + self.count < self.state.status(self.room_id)["mapped"]
        ):
            return
        self.state.publish(
            self.room_id,
            glb(vertices, faces),
            objects,
            {
                "backend": "hydra",
                "coordinate_system": "right_handed_y_up_meters",
                "integrated_frames": self.atlas.frames + self.count,
                "through_sequence": max(self.atlas.through, through_sequence),
                "vertices": len(vertices),
                "triangles": len(faces),
                "batch_ms": (time.perf_counter() - began) * 1000,
                "object_events": list(self.lifecycle.events),
                "loop_constraints": self.submitted_loops,
                "loop_detection": dict(self.loops.status) if self.loops else {},
                "replaying": False,
                "sealed_segments": self.atlas.generation,
                "active_segment_frames": self.count,
                "mapping_frame_limit": None,
                "instance_backend": "esam-e" if "instance_objects" in result else "hydra",
                "instance_timing": result.get("instance_timing", {}),
            },
            self.unpublished,
            evidence,
        )
        self.unpublished.clear()

    def seal(self):
        if self.last_composed is None or not self.segment_sequences:
            return
        self.atlas.seal(*self.last_composed, self.segment_sequences)
        cleanup(self.state.store)
        self.reset()

    def close(self, checkpoint=False):
        if checkpoint:
            self.seal()
        if self.loops:
            self.loops.close()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.mapper.close()
