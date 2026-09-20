import json

import pytest
from pydantic import ValidationError

from htn_backend.voice.lab.memory import Memory


def notes(memory, query=""):
    result = memory.call("recall_notes", {"query": query})
    return json.loads(result["contentItems"][0]["text"])["notes"]


def test_notes_persist_replace_and_stay_in_room(tmp_path):
    path = tmp_path / "notes.sqlite"
    first = Memory(path, "one")
    first.call("remember_note", {"key": "dropoff", "note": "source table"})
    first.call("remember_note", {"key": "dropoff", "note": "delivery table"})
    first.close()
    first.close()
    reopened, other = Memory(path, "one"), Memory(path, "two")
    try:
        assert len(notes(reopened)) == 1
        assert notes(reopened, "DELIVERY")[0]["note"] == "delivery table"
        assert notes(reopened, "drop off")[0]["key"] == "dropoff"
        assert notes(reopened, "drop-off")[0]["key"] == "dropoff"
        assert notes(reopened, "source") == []
        assert notes(other) == []
        assert notes(reopened, "' OR 1=1 --") == []
        with pytest.raises(ValidationError):
            reopened.call("remember_note", {"key": "", "note": "bad"})
    finally:
        reopened.close()
        other.close()
