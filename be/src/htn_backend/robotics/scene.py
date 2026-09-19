"""Evidence-grounded agent context; presentation models are never collision geometry."""

import math
import time

from ..storage.database import StoreError
from .observations import Observations


class Scene:
    def __init__(self, state):
        self.state = state
        self.observations = Observations(state)

    def read(self, room_id):
        with self.state.store.lock:
            status = self.state.status(room_id)
            try:
                snapshot = self.state.snapshot(room_id, include_mesh=False)
            except StoreError as error:
                if error.status != 409:
                    raise
                snapshot = None
            try:
                observation = self.observations.latest(room_id)
            except StoreError as error:
                if error.status != 409:
                    raise
                observation = None
        now = time.time()
        objects = (
            [self.decorate(room_id, obj, now) for obj in snapshot["objects"]] if snapshot else []
        )
        return dict(
            room_id=room_id,
            revision=snapshot["revision"] if snapshot else 0,
            coordinate_system="right_handed_y_up_meters",
            map_publication_age_s=max(0, now - snapshot["updated_at"]) if snapshot else None,
            processing=status,
            observation=observation,
            objects=objects,
            capabilities=dict(
                observe=observation is not None,
                search=True,
                inspect=True,
                navigate=False,
                pick=False,
                place=False,
                stop=False,
            ),
            blockers=[
                "No calibrated robot base or arm executor is connected",
                "Camera pose is not robot base or gripper pose",
                "Collision map and local obstacle-stop controller are not validated",
            ],
            geometry_contract="Objects are partial observed bounds, not complete collision shapes",
        )

    @staticmethod
    def decorate(room_id, obj, now):
        received = obj.get("last_confirmed_received_at")
        age = (
            max(0, now - received)
            if isinstance(received, (int, float)) and math.isfinite(received)
            else None
        )
        return dict(
            **obj,
            confirmation_receipt_age_s=age,
            requires_reobservation=True,
            grasp_ready=False,
            evidence_url=f"/v1/rooms/{room_id}/objects/{obj['object_id']}/evidence.jpg"
            if obj.get("evidence_digest")
            else None,
        )

    def search(self, room_id, query):
        # Current search is explicitly lexical; never advertise embedding retrieval.
        with self.state.store.lock:
            scene = self.read(room_id)
            if not scene["revision"]:
                return dict(revision=0, search="sqlite_fts5", objects=[])
            matches = self.state.search(room_id, query)
            return dict(
                revision=scene["revision"],
                search="sqlite_fts5",
                objects=[self.decorate(room_id, obj, time.time()) for obj in matches],
            )
