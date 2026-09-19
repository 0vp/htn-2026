"""Durable, idempotent skill receipts. No motion is inferred from a queued request."""

import json
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..storage.database import StoreError


class SkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    skill: Literal["inspect", "navigate", "pick", "place", "stop"]
    object_id: str | None = Field(default=None, min_length=1, max_length=120)
    scene_revision: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def target_required(self):
        if self.skill != "stop" and not self.object_id:
            raise ValueError("An explicit object ID is required")
        return self


class Actions:
    def __init__(self, scene):
        self.scene, self.store = scene, scene.state.store
        with self.store.lock, self.store.db:
            self.store.db.executescript("""
                CREATE TABLE IF NOT EXISTS skill_receipts (
                    room_id TEXT NOT NULL REFERENCES rooms(room_id),
                    request_id TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE,
                    request TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(room_id,request_id)
                );
            """)

    def submit(self, room_id, request):
        encoded = request.model_dump_json()
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            self.store.require_room(room_id)
            existing = self.store.db.execute(
                "SELECT request,result FROM skill_receipts WHERE room_id=? AND request_id=?",
                (room_id, request.request_id),
            ).fetchone()
            if existing:
                if existing["request"] != encoded:
                    raise StoreError(409, "Request ID already belongs to a different action")
                return json.loads(existing["result"])
            scene = self.scene.read(room_id)
            obj = next((o for o in scene["objects"] if o["object_id"] == request.object_id), None)
            reasons = []
            if request.skill != "stop":
                if request.scene_revision != scene["revision"]:
                    reasons.append("scene_revision_changed: read the scene again")
                if obj is None:
                    reasons.append("target_not_found: resolve a specific observed object")
                elif obj.get("state") == "location_vacated" or obj.get("visibility") == "absent":
                    reasons.append("target_location_vacated")
            if request.skill != "inspect":
                reasons.append("robot_executor_unavailable: no physical command was dispatched")
            elif obj and not obj.get("evidence_url"):
                reasons.append("visual_evidence_unavailable: record another view")
            result = dict(
                action_id=uuid.uuid4().hex,
                room_id=room_id,
                request_id=request.request_id,
                skill=request.skill,
                object_id=request.object_id,
                scene_revision=scene["revision"],
                state="blocked" if reasons else "completed",
                dispatched=False,
                physical_success=False,
                reasons=reasons,
                result={
                    "object": obj,
                    "meaning": "Stored observation retrieved; not a fresh physical inspection",
                }
                if request.skill == "inspect" and not reasons
                else None,
                created_at=time.time(),
            )
            self.store.db.execute(
                "INSERT INTO skill_receipts VALUES(?,?,?,?,?,?)",
                (
                    room_id,
                    request.request_id,
                    result["action_id"],
                    encoded,
                    json.dumps(result, allow_nan=False),
                    result["created_at"],
                ),
            )
            return result

    def get(self, room_id, action_id):
        with self.store.lock:
            self.store.require_room(room_id)
            row = self.store.db.execute(
                "SELECT result FROM skill_receipts WHERE room_id=? AND action_id=?",
                (room_id, action_id),
            ).fetchone()
            if row is None:
                raise StoreError(404, "Action receipt not found")
            return json.loads(row["result"])
