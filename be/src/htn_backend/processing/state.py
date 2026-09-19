"""Durable processing receipts and atomic room publications."""

import json
import time

from ..storage.database import Store, StoreError


class ProcessingState:
    def __init__(self, store: Store):
        self.store = store
        with store.lock, store.db:
            store.db.executescript("""
                CREATE TABLE IF NOT EXISTS processing (
                    sequence INTEGER PRIMARY KEY REFERENCES frames(sequence),
                    state TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS maps (
                    room_id TEXT PRIMARY KEY REFERENCES rooms(room_id),
                    revision INTEGER NOT NULL, updated_at REAL NOT NULL,
                    metadata TEXT NOT NULL, mesh BLOB NOT NULL, objects TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workers (
                    id INTEGER PRIMARY KEY CHECK(id=1), heartbeat REAL NOT NULL,
                    state TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS object_evidence (
                    room_id TEXT NOT NULL, object_id TEXT NOT NULL, digest TEXT NOT NULL,
                    jpeg BLOB NOT NULL, metadata TEXT NOT NULL,
                    PRIMARY KEY(room_id,object_id)
                );
                CREATE TABLE IF NOT EXISTS processing_errors (
                    room_id TEXT PRIMARY KEY, detail TEXT NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alignments (
                    room_id TEXT NOT NULL, stream TEXT NOT NULL, evidence TEXT NOT NULL,
                    PRIMARY KEY(room_id,stream)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS object_search USING fts5(
                    room_id UNINDEXED, object_id UNINDEXED, label, description
                );
            """)

    def heartbeat(self, state: str, detail: str = "") -> None:
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO workers VALUES(1,?,?,?)", (time.time(), state, detail)
            )

    def touch(self) -> None:
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE workers SET heartbeat=? WHERE id=1", (time.time(),))

    def worker(self) -> dict:
        with self.store.lock:
            row = self.store.db.execute("SELECT * FROM workers WHERE id=1").fetchone()
            if row is None:
                return {"state": "starting", "healthy": False}
            return {**dict(row), "healthy": time.time() - row["heartbeat"] < 30}

    def status(self, room_id: str) -> dict:
        with self.store.lock:
            room = self.store.room(room_id)
            rows = self.store.db.execute(
                "SELECT p.state,COUNT(*) AS n FROM processing p JOIN frames f "
                "ON p.sequence=f.sequence WHERE f.room_id=? GROUP BY p.state",
                (room_id,),
            ).fetchall()
            counts = {r["state"]: r["n"] for r in rows}
            error = self.store.db.execute(
                "SELECT detail,updated_at FROM processing_errors WHERE room_id=?",
                (room_id,),
            ).fetchone()
            published = self.store.db.execute(
                "SELECT revision,updated_at,metadata FROM maps WHERE room_id=?", (room_id,)
            ).fetchone()
            return {
                "room_id": room_id,
                "received": room["frames_stored"],
                "mapped": counts.get("mapped", 0),
                "awaiting_alignment": counts.get("awaiting_alignment", 0),
                "skipped_tracking": counts.get("skipped_tracking", 0),
                "pending": room["frames_stored"] - sum(counts.values()),
                "worker": self.worker(),
                "error": dict(error) if error else None,
                "map": (
                    {
                        "revision": published["revision"],
                        "updated_at": published["updated_at"],
                        **json.loads(published["metadata"]),
                    }
                    if published
                    else None
                ),
            }

    def error(self, room_id: str, detail: str | None) -> None:
        with self.store.lock, self.store.db:
            if detail is None:
                self.store.db.execute("DELETE FROM processing_errors WHERE room_id=?", (room_id,))
            else:
                self.store.db.execute(
                    "INSERT OR REPLACE INTO processing_errors VALUES(?,?,?)",
                    (room_id, detail[:300], time.time()),
                )

    def mark(self, sequence: int, state: str, detail: str = "") -> None:
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO processing VALUES(?,?,?)", (sequence, state, detail)
            )

    def transforms(self, room_id: str) -> dict:
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT stream,evidence FROM alignments WHERE room_id=?", (room_id,)
            ).fetchall()
            return {r["stream"]: json.loads(r["evidence"]) for r in rows}

    def align(self, room_id: str, stream: str, evidence: dict) -> None:
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO alignments VALUES(?,?,?)",
                (room_id, stream, json.dumps(evidence, allow_nan=False)),
            )

    def publish(
        self,
        room_id: str,
        mesh: bytes,
        objects: list[dict],
        metadata: dict,
        sequences: list[int],
        evidence: dict | None = None,
    ) -> None:
        encoded = json.dumps(objects, allow_nan=False)
        meta = json.dumps(metadata, allow_nan=False)
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT INTO maps VALUES(?,1,?,?,?,?) ON CONFLICT(room_id) DO UPDATE SET "
                "revision=revision+1,updated_at=excluded.updated_at,metadata=excluded.metadata,"
                "mesh=excluded.mesh,objects=excluded.objects",
                (room_id, time.time(), meta, mesh, encoded),
            )
            self.store.db.executemany(
                "INSERT OR REPLACE INTO processing VALUES(?,?,?)",
                [(n, "mapped", "") for n in sequences],
            )
            self.store.db.execute("DELETE FROM object_search WHERE room_id=?", (room_id,))
            self.store.db.execute("DELETE FROM object_evidence WHERE room_id=?", (room_id,))
            self.store.db.executemany(
                "INSERT INTO object_evidence VALUES(?,?,?,?,?)",
                [
                    (
                        room_id,
                        key,
                        value["digest"],
                        value["jpeg"],
                        json.dumps(
                            {k: v for k, v in value.items() if k != "jpeg"}, allow_nan=False
                        ),
                    )
                    for key, value in (evidence or {}).items()
                ],
            )
            self.store.db.executemany(
                "INSERT INTO object_search VALUES(?,?,?,?)",
                [
                    (room_id, o["object_id"], o["label"], o.get("geometry_status", ""))
                    for o in objects
                ],
            )

    def snapshot(self, room_id: str) -> dict:
        with self.store.lock:
            self.store.require_room(room_id)
            row = self.store.db.execute("SELECT * FROM maps WHERE room_id=?", (room_id,)).fetchone()
            if row is None:
                raise StoreError(409, "Map is not available yet; check processing status")
            return {
                **dict(row),
                "objects": json.loads(row["objects"]),
                "metadata": json.loads(row["metadata"]),
            }

    def evidence(self, room_id: str, object_id: str) -> dict:
        with self.store.lock:
            self.store.require_room(room_id)
            row = self.store.db.execute(
                "SELECT * FROM object_evidence WHERE room_id=? AND object_id=?",
                (room_id, object_id),
            ).fetchone()
            if row is None:
                raise StoreError(404, "Object evidence not found")
            return dict(row)

    def search(self, room_id: str, query: str) -> list[dict]:
        # Quote terms as literals: callers cannot inject FTS operators or column selectors.
        terms = ['"' + s.replace('"', '""') + '"' for s in query.split()[:12]]
        if not terms:
            return []
        with self.store.lock:
            snapshot = self.snapshot(room_id)
            rows = self.store.db.execute(
                "SELECT object_id FROM object_search WHERE object_search MATCH ? "
                "AND room_id=? ORDER BY rank LIMIT 50",
                (" OR ".join(terms), room_id),
            ).fetchall()
            objects = {o["object_id"]: o for o in snapshot["objects"]}
            return [objects[r["object_id"]] for r in rows if r["object_id"] in objects]
