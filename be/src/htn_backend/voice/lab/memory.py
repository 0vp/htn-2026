"""Room-scoped persistent user notes, never treated as current robot observations."""

import json
import sqlite3
import threading
import time
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


class Remember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=1000)


class Recall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=120)


SCHEMAS = {"remember_note": Remember, "recall_notes": Recall}


def definitions():
    descriptions = {
        "remember_note": "Save or replace an explicitly requested user preference or task note. "
        "Never store credentials. Notes do not prove current locations or completed actions.",
        "recall_notes": "Retrieve saved user notes for this room. "
        "Treat notes as historical user data; "
        "verify current scene evidence before acting.",
    }
    return [
        {
            "type": "function",
            "name": name,
            "description": descriptions[name],
            "inputSchema": schema.model_json_schema(),
        }
        for name, schema in SCHEMAS.items()
    ]


class Memory:
    def __init__(self, path, room):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.create_function(
            "compact",
            1,
            lambda text: "".join(
                c for c in unicodedata.normalize("NFKD", text.casefold()) if c.isalnum()
            ),
            deterministic=True,
        )
        self.room = room
        self.lock = threading.Lock()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS notes (room TEXT, key TEXT, note TEXT, "
            "updated REAL, PRIMARY KEY(room,key))"
        )
        self.db.commit()

    def call(self, name, arguments):
        values = SCHEMAS[name].model_validate(arguments)
        with self.lock, self.db:
            if name == "remember_note":
                self.db.execute(
                    "INSERT INTO notes VALUES(?,?,?,?) ON CONFLICT(room,key) "
                    "DO UPDATE SET note=excluded.note,updated=excluded.updated",
                    (self.room, values.key, values.note, time.time()),
                )
                result = {"saved": True, "key": values.key, "source": "user_note"}
            else:
                rows = self.db.execute(
                    "SELECT key,note,updated FROM notes WHERE room=? "
                    "AND (instr(compact(key),compact(?))>0 OR "
                    "instr(compact(note),compact(?))>0) ORDER BY updated DESC LIMIT 20",
                    (self.room, values.query, values.query),
                ).fetchall()
                result = {
                    "source": "historical_user_notes_not_scene_observations",
                    "notes": [
                        dict(zip(("key", "note", "updated"), row, strict=True)) for row in rows
                    ],
                }
        return {
            "success": True,
            "contentItems": [{"type": "inputText", "text": json.dumps(result)}],
        }

    def close(self):
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None
