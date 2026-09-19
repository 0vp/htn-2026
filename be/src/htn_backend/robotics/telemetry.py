"""Reported ESP32 state, kept separate from calibrated robot pose and execution feedback."""

import json
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..api.models import DeviceID
from ..storage.database import StoreError


class Angles(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    shoulder: float = Field(ge=-180, le=180)
    elbow: float = Field(ge=-180, le=180)
    wrist: float = Field(ge=-180, le=180)


class RPM(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    left: float
    right: float


class FirmwareTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    type: Literal["telemetry"]
    packVolts: float = Field(ge=0, le=100)
    ampsEstimate: float = Field(ge=0, le=1000)
    servoDeg: Angles
    winchPos: tuple[float, float, float]
    limits: tuple[tuple[bool, bool], tuple[bool, bool], tuple[bool, bool]]
    loopHz: float = Field(ge=0)
    uptimeS: int = Field(ge=0)
    heapKb: int = Field(ge=0)
    rpm: RPM | None = None
    odometerM: float | None = None


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: DeviceID
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    sequence: int = Field(ge=0, strict=True)
    telemetry: FirmwareTelemetry


class RobotState:
    def __init__(self, store):
        self.store = store
        with store.lock, store.db:
            store.db.execute("""CREATE TABLE IF NOT EXISTS robot_telemetry (
                room_id TEXT NOT NULL REFERENCES rooms(room_id), device_id TEXT NOT NULL,
                session_id TEXT NOT NULL, sequence INTEGER NOT NULL, received_at REAL NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(room_id,device_id)
            )""")

    def publish(self, room_id, report):
        payload = report.telemetry.model_dump_json()
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            self.store.require_room(room_id)
            row = self.store.db.execute(
                "SELECT * FROM robot_telemetry WHERE room_id=? AND device_id=?",
                (room_id, report.device_id),
            ).fetchone()
            if row and row["session_id"] == report.session_id:
                if report.sequence < row["sequence"]:
                    raise StoreError(409, "Telemetry sequence is older than the current report")
                if report.sequence == row["sequence"]:
                    if payload != row["payload"]:
                        raise StoreError(409, "Telemetry sequence already has different content")
                    return dict(accepted=True, duplicate=True, received_at=row["received_at"])
            if row is None:
                count = self.store.db.execute(
                    "SELECT COUNT(*) FROM robot_telemetry WHERE room_id=?", (room_id,)
                ).fetchone()[0]
                if count >= 16:
                    raise StoreError(409, "Room robot telemetry device limit reached")
            now = time.time()
            self.store.db.execute(
                "INSERT OR REPLACE INTO robot_telemetry VALUES(?,?,?,?,?,?)",
                (room_id, report.device_id, report.session_id, report.sequence, now, payload),
            )
            return dict(accepted=True, duplicate=False, received_at=now)

    def read(self, room_id):
        with self.store.lock:
            self.store.require_room(room_id)
            rows = self.store.db.execute(
                "SELECT * FROM robot_telemetry WHERE room_id=? ORDER BY received_at DESC",
                (room_id,),
            ).fetchall()
        now = time.time()
        return [
            dict(
                device_id=r["device_id"],
                session_id=r["session_id"],
                sequence=r["sequence"],
                receipt_age_s=max(0, now - r["received_at"]),
                recently_received=now - r["received_at"] < 2,
                telemetry=json.loads(r["payload"]),
                robot_pose=None,
                source="reported ESP32 telemetry; not authenticated execution feedback",
                servo_feedback="commanded estimate, not measured joint encoders",
                navigation_calibrated=False,
                physical_success=None,
            )
            for r in rows
        ]
