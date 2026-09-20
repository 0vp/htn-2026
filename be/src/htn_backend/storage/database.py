"""Transactional room membership and lossless frame storage."""

import hashlib
import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from ..capture.codec import encode
from ..capture.frame import Frame
from . import geography
from .counters import initialize

MAX_ROOMS = 128
MAX_DEVICES = 16
MAX_BYTES = 4_000_000_000
MIN_FREE_BYTES = 2_000_000_000


class StoreError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(detail)


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "rooms.sqlite3", check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                created_at REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS devices (
                room_id TEXT NOT NULL REFERENCES rooms(room_id), device_id TEXT NOT NULL,
                name TEXT NOT NULL, joined_at REAL NOT NULL,
                PRIMARY KEY(room_id, device_id)
            );
            CREATE TABLE IF NOT EXISTS frames (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL, device_id TEXT NOT NULL,
                session_id TEXT NOT NULL, epoch INTEGER NOT NULL, frame_id INTEGER NOT NULL,
                header TEXT NOT NULL, sha256 TEXT NOT NULL, payload BLOB NOT NULL,
                bytes INTEGER NOT NULL, received_at REAL NOT NULL,
                FOREIGN KEY(room_id, device_id) REFERENCES devices(room_id, device_id),
                UNIQUE(room_id, device_id, session_id, epoch, frame_id)
            );
            CREATE INDEX IF NOT EXISTS room_frames ON frames(room_id, sequence);
            CREATE TABLE IF NOT EXISTS totals (
                id INTEGER PRIMARY KEY CHECK(id=1), bytes INTEGER NOT NULL, frames INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO totals VALUES(1, 0, 0);
        """)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            room_columns = {r[1] for r in self.db.execute("PRAGMA table_info(rooms)")}
            if "leader_device_id" not in room_columns:
                self.db.execute("ALTER TABLE rooms ADD COLUMN leader_device_id TEXT")
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(frames)")}
            if "archived" not in columns:
                self.db.execute("ALTER TABLE frames ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS room_active_frames ON frames(room_id,archived,sequence)"
            )

            initialize(self.db)
            geography.initialize(self.db)
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS retention_candidates "
                "ON frames(received_at,sequence) WHERE archived=1 AND length(payload)>0"
            )

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def room(self, room_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM rooms WHERE room_id=?", (room_id,)).fetchone()
            if row is None:
                raise StoreError(404, "Room not found")
            stats = self.db.execute(
                "SELECT received AS frames_stored, retained AS raw_frames_retained, "
                "bytes AS bytes_stored FROM room_counts WHERE room_id=?",
                (room_id,),
            ).fetchone()
            stats = (
                dict(stats)
                if stats
                else dict(frames_stored=0, raw_frames_retained=0, bytes_stored=0)
            )
            devices = self.db.execute(
                "SELECT device_id,name,joined_at FROM devices WHERE room_id=? ORDER BY joined_at",
                (room_id,),
            ).fetchall()
            return {
                **dict(row),
                "closed": bool(row["closed"]),
                **dict(stats),
                "devices": [dict(d) for d in devices],
                "geography": geography.response(self.db, room_id),
            }

    def rooms(self) -> list[dict]:
        with self.lock:
            ids = self.db.execute("SELECT room_id FROM rooms ORDER BY created_at DESC").fetchall()
            return [self.room(row[0]) for row in ids]

    def create(self, name: str, device_id: str | None = None) -> dict:
        with self.lock, self.db:
            if self.db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] >= MAX_ROOMS:
                raise StoreError(409, "Room limit reached")
            while True:
                room_id = uuid.uuid4().hex[:8].upper()
                if not self.db.execute(
                    "SELECT 1 FROM rooms WHERE room_id=?", (room_id,)
                ).fetchone():
                    break
            now = time.time()
            self.db.execute(
                "INSERT INTO rooms(room_id,name,created_at,closed,leader_device_id) "
                "VALUES(?,?,?,0,?)",
                (room_id, name, now, device_id),
            )
            if device_id is not None:
                self.db.execute(
                    "INSERT INTO devices VALUES(?,?,?,?)", (room_id, device_id, "iPhone", now)
                )
        return self.room(room_id)

    def join(self, room_id: str, device_id: str, name: str) -> dict:
        with self.lock, self.db:
            room = self.room(room_id)
            if room["closed"]:
                raise StoreError(409, "Room is closed")
            existing = any(d["device_id"] == device_id for d in room["devices"])
            if not existing and len(room["devices"]) >= MAX_DEVICES:
                raise StoreError(409, "Device limit reached")
            self.db.execute(
                "INSERT INTO devices VALUES(?,?,?,?) ON CONFLICT(room_id,device_id) "
                "DO UPDATE SET name=excluded.name",
                (room_id, device_id, name, time.time()),
            )
        return self.room(room_id)

    def require_room(self, room_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM rooms WHERE room_id=?", (room_id,)).fetchone()
        if row is None:
            raise StoreError(404, "Room not found")
        return row

    def member(self, room_id: str, device_id: str) -> None:
        with self.lock:
            self.require_room(room_id)
            if not self.db.execute(
                "SELECT 1 FROM devices WHERE room_id=? AND device_id=?",
                (room_id, device_id),
            ).fetchone():
                raise StoreError(409, "Join the room before uploading")

    def close_room(self, room_id: str) -> dict:
        with self.lock, self.db:
            self.require_room(room_id)
            self.db.execute("UPDATE rooms SET closed=1 WHERE room_id=?", (room_id,))
        return self.room(room_id)

    def save(self, room_id: str, device_id: str, frame: Frame, payload: bytes) -> dict:
        # Canonical content makes uncompressed/compressed retries equivalent.
        digest = hashlib.sha256(encode(frame)).hexdigest()
        h = frame.header
        identity = (room_id, device_id, h.session_id, h.epoch, h.frame_id)
        with self.lock, self.db:
            self.member(room_id, device_id)
            prior = self.db.execute(
                "SELECT sequence,sha256,received_at,bytes FROM frames WHERE "
                "room_id=? AND device_id=? AND session_id=? AND epoch=? AND frame_id=?",
                identity,
            ).fetchone()
            if prior:
                if prior["sha256"] != digest:
                    raise StoreError(409, "Frame identity already contains different data")
                return {**dict(prior), "stored": True, "duplicate": True}
            if self.require_room(room_id)["closed"]:
                raise StoreError(409, "Room is closed")
            totals = self.db.execute("SELECT * FROM totals WHERE id=1").fetchone()
            if totals["bytes"] + len(payload) > MAX_BYTES:
                raise StoreError(507, "Capture storage limit reached")
            if shutil.disk_usage(self.root).free < MIN_FREE_BYTES + 2 * len(payload):
                raise StoreError(507, "Insufficient disk space")
            now = time.time()
            cursor = self.db.execute(
                "INSERT INTO frames(room_id,device_id,session_id,epoch,frame_id,header,"
                "sha256,payload,bytes,received_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (*identity, h.model_dump_json(), digest, payload, len(payload), now),
            )
            self.db.execute(
                "UPDATE totals SET bytes=bytes+?,frames=frames+1 WHERE id=1", (len(payload),)
            )
            geography.save(self.db, room_id, device_id, h, cursor.lastrowid, now)
            receipt = dict(
                sequence=cursor.lastrowid,
                sha256=digest,
                bytes=len(payload),
                received_at=now,
                stored=True,
                duplicate=False,
            )
        # The transaction has committed before an acknowledgement can leave the server.
        return receipt

    def frames(self, room_id: str, after: int, limit: int) -> list[dict]:
        with self.lock:
            self.require_room(room_id)
            rows = self.db.execute(
                "SELECT sequence,device_id,header,bytes,received_at,sha256, "
                "length(payload)>0 AS raw_available FROM frames "
                "WHERE room_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (room_id, after, limit),
            ).fetchall()
            return [{**dict(r), "header": json.loads(r["header"])} for r in rows]

    def active_frames(self, room_id: str, after: int, limit: int) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT sequence,device_id,header,bytes,received_at,sha256 FROM frames "
                "WHERE room_id=? AND archived=0 AND sequence>? ORDER BY sequence LIMIT ?",
                (room_id, after, limit),
            ).fetchall()
            return [{**dict(r), "header": json.loads(r["header"])} for r in rows]

    def payload(self, room_id: str, sequence: int) -> bytes:
        with self.lock:
            self.require_room(room_id)
            row = self.db.execute(
                "SELECT payload FROM frames WHERE room_id=? AND sequence=?", (room_id, sequence)
            ).fetchone()
            if row is None:
                raise StoreError(404, "Frame not found")
            if not row[0]:
                raise StoreError(410, "Raw capture cleaned after durable map checkpoint")
            return bytes(row[0])
