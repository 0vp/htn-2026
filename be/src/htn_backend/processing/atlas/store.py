"""Atomic cumulative surface checkpoints independent of disposable native workers."""

import json
import time

from .geometry import decode, encode, merge, mesh, tiles
from .objects import combine


class Atlas:
    def __init__(self, store, room_id):
        self.store, self.room_id = store, room_id
        with store.lock, store.db:
            store.db.executescript("""
                CREATE TABLE IF NOT EXISTS atlas_state (
                    room_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                    frames INTEGER NOT NULL, through_sequence INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS atlas_tiles (
                    room_id TEXT NOT NULL, tile TEXT NOT NULL, surface BLOB NOT NULL,
                    PRIMARY KEY(room_id,tile)
                );
                CREATE TABLE IF NOT EXISTS atlas_objects (
                    room_id TEXT NOT NULL, object_id TEXT NOT NULL, object TEXT NOT NULL,
                    evidence BLOB, metadata TEXT,
                    PRIMARY KEY(room_id,object_id)
                );
            """)
            store.db.execute("INSERT OR IGNORE INTO atlas_state VALUES(?,0,0,0)", (room_id,))
        self.load()

    def load(self):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT * FROM atlas_state WHERE room_id=?", (self.room_id,)
            ).fetchone()
            self.generation, self.frames, self.through = (
                row["generation"],
                row["frames"],
                row["through_sequence"],
            )
            rows = self.store.db.execute(
                "SELECT tile,surface FROM atlas_tiles WHERE room_id=?", (self.room_id,)
            ).fetchall()
            self.groups = {r["tile"]: decode(r["surface"]) for r in rows}
            rows = self.store.db.execute(
                "SELECT * FROM atlas_objects WHERE room_id=?", (self.room_id,)
            ).fetchall()
            self.objects = [json.loads(r["object"]) for r in rows]
            self.evidence = {
                r["object_id"]: json.loads(r["metadata"]) | {"jpeg": bytes(r["evidence"])}
                for r in rows
                if r["evidence"] is not None
            }

    def compose(self, vertices, faces, objects, evidence):
        changed = tiles(vertices, faces)
        groups = dict(self.groups)
        for key, triangles in changed.items():
            groups[key] = merge(groups[key], triangles) if key in groups else triangles
        combined, updates = combine(self.objects, objects, evidence, self.generation)
        return (*mesh(groups), combined, self.evidence | updates, groups)

    def seal(self, groups, objects, evidence, sequences):
        if not sequences:
            return
        placeholders = ",".join("?" for _ in sequences)
        with self.store.lock, self.store.db:
            count = self.store.db.execute(
                f"SELECT COUNT(*) FROM frames WHERE room_id=? AND archived=0 AND "
                f"sequence IN ({placeholders})",
                (self.room_id, *sequences),
            ).fetchone()[0]
            if count != len(sequences):
                raise RuntimeError("Segment checkpoint does not own every capture")
            self.store.db.executemany(
                "INSERT OR REPLACE INTO atlas_tiles VALUES(?,?,?)",
                [(self.room_id, key, encode(value)) for key, value in groups.items()],
            )
            self.store.db.execute("DELETE FROM atlas_objects WHERE room_id=?", (self.room_id,))
            self.store.db.executemany(
                "INSERT INTO atlas_objects VALUES(?,?,?,?,?)",
                [
                    (
                        self.room_id,
                        obj["object_id"],
                        json.dumps(obj, allow_nan=False),
                        evidence.get(obj["object_id"], {}).get("jpeg"),
                        json.dumps(
                            {k: v for k, v in evidence[obj["object_id"]].items() if k != "jpeg"},
                            allow_nan=False,
                        )
                        if obj["object_id"] in evidence
                        else None,
                    )
                    for obj in objects
                ],
            )
            self.store.db.execute(
                f"UPDATE frames SET archived=1 WHERE room_id=? AND sequence IN ({placeholders})",
                (self.room_id, *sequences),
            )
            self.store.db.execute(
                "UPDATE atlas_state SET generation=generation+1, "
                "frames=frames+?,through_sequence=MAX(through_sequence,?) "
                "WHERE room_id=?",
                (count, max(sequences), self.room_id),
            )
            published = self.store.db.execute(
                "SELECT metadata FROM maps WHERE room_id=?", (self.room_id,)
            ).fetchone()
            if published:
                metadata = json.loads(published["metadata"])
                if metadata.get("integrated_frames") == self.frames + count:
                    metadata.update(sealed_segments=self.generation + 1, active_segment_frames=0)
                    self.store.db.execute(
                        "UPDATE maps SET metadata=?,revision=revision+1, "
                        "updated_at=? WHERE room_id=?",
                        (json.dumps(metadata, allow_nan=False), time.time(), self.room_id),
                    )
        self.load()
