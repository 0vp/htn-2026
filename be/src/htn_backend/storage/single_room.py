"""Single-room deployment: HTN_ROOM_ID pins the whole service to one always-open room.

Every client auto-joins that room, so creating returns it, closing is ignored and rows that
belong to any other room are purged at startup.
"""

import os
import re
import sqlite3
import time


def configured() -> str | None:
    room_id = os.environ.get("HTN_ROOM_ID", "").strip().upper()
    if room_id and not re.fullmatch(r"[A-F0-9]{8}", room_id):
        raise ValueError("HTN_ROOM_ID must be 8 hex characters")
    return room_id or None


def ensure(db: sqlite3.Connection, room_id: str) -> None:
    """Keep only `room_id`, open. Runs before foreign keys matter to any other connection."""
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    scoped = [
        t
        for t in tables
        if t != "rooms" and any(c[1] == "room_id" for c in db.execute(f'PRAGMA table_info("{t}")'))
    ]
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        with db:
            for table in scoped:
                db.execute(f'DELETE FROM "{table}" WHERE room_id<>?', (room_id,))
            db.execute("DELETE FROM rooms WHERE room_id<>?", (room_id,))
            db.execute(
                "INSERT INTO rooms(room_id,name,created_at,closed,leader_device_id) "
                "VALUES(?,?,?,0,NULL) ON CONFLICT(room_id) DO UPDATE SET closed=0",
                (room_id, "World", time.time()),
            )
            # The global byte budget must forget the purged rooms or uploads hit the cap early.
            db.execute(
                "UPDATE totals SET bytes=(SELECT COALESCE(SUM(length(payload)),0) FROM frames) "
                "WHERE id=1"
            )
    finally:
        db.execute("PRAGMA foreign_keys=ON")
