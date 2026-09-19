"""Sparse spatial reference views survive raw-capture retention."""

import numpy as np

from ...capture.codec import decode, encode


def bucket(frame):
    pose = np.array(frame.header.camera_to_world).reshape(4, 4, order="F")
    cell = np.floor(pose[:3, 3] / 2).astype(int)
    yaw = int(np.floor(np.arctan2(pose[0, 2], pose[2, 2]) / (np.pi / 4)))
    return ",".join(map(str, [*cell, yaw]))


class References:
    def __init__(self, store, room_id):
        self.store, self.room_id = store, room_id
        with store.lock, store.db:
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS alignment_references ("
                "room_id TEXT NOT NULL,sequence INTEGER NOT NULL,payload BLOB NOT NULL,"
                'bucket TEXT NOT NULL DEFAULT "",PRIMARY KEY(room_id,sequence))'
            )
            columns = {r[1] for r in store.db.execute("PRAGMA table_info(alignment_references)")}
            if "bucket" not in columns:
                store.db.execute(
                    'ALTER TABLE alignment_references ADD COLUMN bucket TEXT NOT NULL DEFAULT ""'
                )
                rows = store.db.execute(
                    "SELECT room_id,sequence,payload FROM alignment_references"
                ).fetchall()
                store.db.executemany(
                    "UPDATE alignment_references SET bucket=? WHERE room_id=? AND sequence=?",
                    [(bucket(decode(r["payload"])), r["room_id"], r["sequence"]) for r in rows],
                )

    def frames(self, before=None, limit=24):
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT sequence,payload FROM alignment_references "
                "WHERE room_id=? AND sequence<? ORDER BY sequence DESC LIMIT ?",
                (self.room_id, before if before is not None else 2**63 - 1, limit),
            ).fetchall()
        return [(r["sequence"], decode(r["payload"])) for r in reversed(rows)]

    def ids(self):
        with self.store.lock:
            return {
                r[0]
                for r in self.store.db.execute(
                    "SELECT sequence FROM alignment_references "
                    "WHERE room_id=? ORDER BY sequence DESC LIMIT 24",
                    (self.room_id,),
                )
            }

    def save(self, sequence, frame):
        cell = bucket(frame)
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO alignment_references VALUES(?,?,?,?)",
                (self.room_id, sequence, encode(frame), cell),
            )
            # Replace redundant views, not all old regions. Larger maps retain sparse
            # visual anchors for places last visited long ago.
            self.store.db.execute(
                "DELETE FROM alignment_references WHERE room_id=? AND bucket=? "
                "AND sequence NOT IN (SELECT sequence FROM alignment_references WHERE room_id=? "
                "AND bucket=? ORDER BY sequence DESC LIMIT 2)",
                (self.room_id, cell, self.room_id, cell),
            )
