"""Immutable camera observations independent of the slower mapping queue."""

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

    def latest(self, room_id, device_id=None):
        with self.store.lock:
            self.store.require_room(room_id)
            predicate = " AND device_id=?" if device_id else ""
            params = (room_id, device_id) if device_id else (room_id,)
            row = self.store.db.execute(
                "SELECT sequence,device_id,header,received_at FROM frames "
                f"WHERE room_id=? AND length(payload)>0{predicate} "
                "ORDER BY sequence DESC LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                raise StoreError(409, "No retained camera observation available")
            value = dict(row)
            value["header"] = json.loads(row["header"])
            alignment = self.state.transforms(room_id).get(stream_key(value), {})
        header = value.pop("header")
        pose = np.array(header["camera_to_world"]).reshape(4, 4, order="F")
        transform = alignment.get("room_from_local")
        value.update(
            receipt_age_s=max(0, time.time() - row["received_at"]),
            capture_timestamp_s=header["timestamp_s"],
            capture_clock="device; not synchronized to server wall time",
            capture_age_s=None,
            session_id=header["session_id"],
            epoch=header["epoch"],
            frame_id=header["frame_id"],
            tracking=header["tracking"],
            camera_convention=header["camera_convention"],
            room_from_camera=(np.array(transform).reshape(4, 4, order="F") @ pose).tolist()
            if transform is not None
            else None,
            pose_layout="row_major",
            pose_source="registered ARKit; not loop-corrected",
            robot_pose=None,
            rgb_available=bool(header["rgb_bytes"]),
            image_url=f"/v1/rooms/{room_id}/observations/{row['sequence']}/image.jpg",
        )
        return value

    def image(self, room_id, sequence):
        frame = decode(self.store.payload(room_id, sequence))
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
