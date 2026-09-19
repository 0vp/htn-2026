"""Camera observations and retained reference views independent of the mapping queue."""

import hashlib
import io
import json
import time

import numpy as np
from PIL import Image

from ..capture.codec import decode
from ..perception.orientation import upright_quarter_turns
from ..processing.alignment import stream_key
from ..storage.database import StoreError


class Observations:
    def __init__(self, state):
        self.state, self.store = state, state.store

    def has_references(self):
        return (
            self.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='alignment_references'"
            ).fetchone()
            is not None
        )

    def reference(self, room_id, sequence):
        if not self.has_references():
            return None
        row = self.store.db.execute(
            "SELECT payload FROM alignment_references WHERE room_id=? AND sequence=?",
            (room_id, sequence),
        ).fetchone()
        return bytes(row[0]) if row else None

    def load(self, room_id, sequence):
        """Reference payload poses are already in room coordinates; never transform twice."""
        with self.store.lock:
            self.store.require_room(room_id)
            row = self.store.db.execute(
                "SELECT sequence,device_id,header,received_at,payload FROM frames "
                "WHERE room_id=? AND sequence=?",
                (room_id, sequence),
            ).fetchone()
            if row is None:
                raise StoreError(404, "Observation not found in this room")
            value = dict(row)
            payload = value.pop("payload")
            retained = not bool(payload)
            if retained:
                payload = self.reference(room_id, sequence)
            if not payload:
                raise StoreError(410, "Capture cleaned and no reference view retained")
            frame = decode(payload)
            value["header"] = json.loads(value["header"])
            alignment = self.state.transforms(room_id).get(stream_key(value), {})
        pose = np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
        transform = alignment.get("room_from_local")
        room_pose = (
            pose
            if retained
            else (
                np.array(transform).reshape(4, 4, order="F") @ pose
                if transform is not None
                else None
            )
        )
        value["room_from_camera"] = room_pose.tolist() if room_pose is not None else None
        value["storage_source"] = "retained_reference" if retained else "raw_capture"
        return frame, value

    def metadata(self, room_id, sequence):
        frame, value = self.load(room_id, sequence)
        value.pop("header")
        header = frame.header
        value.update(
            receipt_age_s=max(0, time.time() - value["received_at"]),
            capture_timestamp_s=header.timestamp_s,
            capture_clock="device; not synchronized to server wall time",
            capture_age_s=None,
            session_id=header.session_id,
            epoch=header.epoch,
            frame_id=header.frame_id,
            tracking=header.tracking,
            camera_convention=header.camera_convention,
            pose_layout="row_major",
            pose_source="registered capture; not loop-corrected",
            robot_pose=None,
            rgb_available=bool(header.rgb_bytes),
            image_url=f"/v1/rooms/{room_id}/observations/{sequence}/image.jpg",
        )
        return value

    def latest(self, room_id, device_id=None):
        with self.store.lock:
            self.store.require_room(room_id)
            predicate = " AND device_id=?" if device_id else ""
            params = (room_id, device_id) if device_id else (room_id,)
            retained = ""
            if self.has_references():
                retained = (
                    " OR sequence IN (SELECT sequence FROM alignment_references "
                    "WHERE room_id=frames.room_id)"
                )
            row = self.store.db.execute(
                "SELECT sequence FROM frames "
                f"WHERE room_id=? AND (length(payload)>0{retained}){predicate} "
                "ORDER BY sequence DESC LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                raise StoreError(409, "No raw capture or retained reference observation available")
            return self.metadata(room_id, row["sequence"])

    def history(self, room_id, before=2**63 - 1):
        with self.store.lock:
            self.store.require_room(room_id)
            if not self.has_references():
                return {"views": [], "next_before": None}
            rows = self.store.db.execute(
                "SELECT sequence FROM alignment_references WHERE room_id=? AND sequence<? "
                "ORDER BY sequence DESC LIMIT 8",
                (room_id, before),
            ).fetchall()
            views = [self.metadata(room_id, r["sequence"]) for r in rows]
        return {
            "views": views,
            "next_before": rows[-1]["sequence"] if len(rows) == 8 else None,
            "meaning": "Sparse historical alignment views, not a live camera stream",
        }

    def image(self, room_id, sequence):
        frame, _ = self.load(room_id, sequence)
        if not frame.rgb_jpeg:
            raise StoreError(404, "Observation has no RGB image")
        with Image.open(io.BytesIO(frame.rgb_jpeg)) as image:
            photo = image.convert("RGB").rotate(
                90 * upright_quarter_turns(frame.header), expand=True
            )
            photo.thumbnail((1024, 1024))
            stream = io.BytesIO()
            photo.save(stream, format="JPEG", quality=90)
        data = stream.getvalue()
        return data, hashlib.sha256(data).hexdigest()
