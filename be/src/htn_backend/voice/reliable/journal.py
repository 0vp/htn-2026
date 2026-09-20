"""Durable, ordered PCM ingestion. Acknowledgments mean SQLite FULL commit."""

import hashlib
import sqlite3
import threading
import time
from functools import wraps
from pathlib import Path


def serialized(cls):
    for name, method in list(vars(cls).items()):
        if callable(method) and not name.startswith("_"):

            def wrap(fn):
                @wraps(fn)
                def locked(self, *args, **kwargs):
                    with self.lock:
                        return fn(self, *args, **kwargs)

                return locked

            setattr(cls, name, wrap(method))
    return cls


@serialized
class Journal:
    def __init__(self, path: Path):
        self.lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, room TEXT, device TEXT, request TEXT, codex INTEGER,
            created REAL, ended INTEGER DEFAULT 0, UNIQUE(room,device,request));
          CREATE TABLE IF NOT EXISTS chunks (
            session TEXT, seq INTEGER, pcm BLOB, digest TEXT, PRIMARY KEY(session,seq));
          CREATE TABLE IF NOT EXISTS turns (
            session TEXT, first INTEGER, last INTEGER, transcript TEXT,
            action TEXT DEFAULT 'pending',
            result TEXT, PRIMARY KEY(session,first));
        """)

    def create(self, ident, room, device, request, codex):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?,?,0)",
                (ident, room, device, request, int(codex), time.time()),
            )
        return self.db.execute(
            "SELECT id FROM sessions WHERE room=? AND device=? AND request=?",
            (room, device, request),
        ).fetchone()[0]

    def session(self, ident):
        row = self.db.execute(
            "SELECT room,device,codex,ended FROM sessions WHERE id=?", (ident,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown audio session")
        return row

    def next_seq(self, ident):
        return self.db.execute(
            "SELECT COALESCE(MAX(seq)+1,0) FROM chunks WHERE session=?", (ident,)
        ).fetchone()[0]

    def append(self, ident, seq, pcm):
        if type(seq) is not int or seq < 0 or not pcm or len(pcm) > 24000 or len(pcm) % 2:
            raise ValueError("Invalid numbered PCM16 chunk")
        digest = hashlib.sha256(pcm).hexdigest()
        old = self.db.execute(
            "SELECT digest FROM chunks WHERE session=? AND seq=?", (ident, seq)
        ).fetchone()
        if old:
            if old[0] != digest:
                raise ValueError("Audio sequence reused with different content")
            return self.next_seq(ident)
        if self.session(ident)[3]:
            raise ValueError("Audio session already ended")
        if seq != self.next_seq(ident):
            raise ValueError("Audio gap: replay from acknowledged sequence")
        size = self.db.execute(
            "SELECT COALESCE(SUM(length(pcm)),0) FROM chunks WHERE session=?", (ident,)
        ).fetchone()[0]
        if size + len(pcm) > 48_000 * 1800:
            raise ValueError("Audio storage limit reached; end this conversation")
        with self.db:
            self.db.execute("INSERT INTO chunks VALUES (?,?,?,?)", (ident, seq, pcm, digest))
        return seq + 1

    def chunk(self, ident, seq):
        row = self.db.execute(
            "SELECT pcm FROM chunks WHERE session=? AND seq=?", (ident, seq)
        ).fetchone()
        return row[0] if row else None

    def completed(self, ident):
        return self.db.execute(
            "SELECT COALESCE(MAX(last)+1,0) FROM turns WHERE session=?", (ident,)
        ).fetchone()[0]

    def finalize(self, ident, first, last, text, action="pending"):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO turns(session,first,last,transcript,action) "
                "VALUES (?,?,?,?,?)",
                (ident, first, last, text, action),
            )

    def snapshot(self, ident):
        rows = self.db.execute(
            "SELECT first,transcript,action,result FROM turns WHERE session=? ORDER BY first",
            (ident,),
        ).fetchall()
        return [{"id": str(r[0]), "text": r[1], "action": r[2], "result": r[3]} for r in rows]

    def claim(self, ident, first):
        # Persist before invoking external actions. Unknown outcomes are never auto-replayed.
        with self.db:
            return (
                self.db.execute(
                    "UPDATE turns SET action='running' "
                    "WHERE session=? AND first=? AND action='pending'",
                    (ident, first),
                ).rowcount
                == 1
            )

    def result(self, ident, first, text, state="done"):
        with self.db:
            self.db.execute(
                "UPDATE turns SET action=?,result=? WHERE session=? AND first=?",
                (state, text, ident, first),
            )

    def seal_tail(self, ident):
        with self.db:
            self.db.execute(
                "UPDATE turns SET action='pending' WHERE session=? AND action='fragment' "
                "AND first=(SELECT MAX(first) FROM turns WHERE session=?)",
                (ident, ident),
            )

    def reopen(self, ident):
        with self.db:
            self.db.execute("UPDATE sessions SET ended=0 WHERE id=?", (ident,))

    def end(self, ident):
        with self.db:
            self.db.execute("UPDATE sessions SET ended=1 WHERE id=?", (ident,))

    def prune(self):
        # Retain unfinished calls for recovery, delete completed audio after one day.
        with self.db:
            ids = self.db.execute(
                "SELECT id FROM sessions WHERE ended=1 AND created<?", (time.time() - 86400,)
            ).fetchall()
            for (ident,) in ids:
                for table in ("chunks", "turns", "sessions"):
                    self.db.execute(
                        f"DELETE FROM {table} WHERE {'id' if table == 'sessions' else 'session'}=?",
                        (ident,),
                    )

    def close(self):
        self.db.close()
