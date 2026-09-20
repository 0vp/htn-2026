import concurrent.futures
import sqlite3

import pytest

from htn_backend.voice.reliable.journal import Journal


def test_reconnect_gap_conflict_and_restart(tmp_path):
    path = tmp_path / "audio.sqlite"
    journal = Journal(path)
    ident = journal.create("one", "room", "phone", "request", False)
    assert journal.create("unused", "room", "phone", "request", False) == ident
    chunks = [bytes([i, 0]) * 4800 for i in range(20)]
    with pytest.raises(ValueError, match="gap"):
        journal.append(ident, 1, chunks[1])
    for seq, chunk in enumerate(chunks):
        assert journal.append(ident, seq, chunk) == seq + 1
        # Simulated lost ACK: exact replay must not append twice.
        assert journal.append(ident, seq, chunk) == seq + 1
    with pytest.raises(ValueError, match="different"):
        journal.append(ident, 0, b"\x01\x01")
    journal.close()
    restored = Journal(path)
    assert restored.next_seq(ident) == len(chunks)
    assert b"".join(restored.chunk(ident, i) for i in range(20)) == b"".join(chunks)
    restored.finalize(ident, 0, 19, "complete speech")
    assert restored.completed(ident) == 20
    with concurrent.futures.ThreadPoolExecutor() as pool:
        assert sum(pool.map(lambda _: restored.claim(ident, 0), range(32))) == 1
    restored.close()
    restored = Journal(path)
    assert not restored.claim(ident, 0)  # Unknown external execution never retries.
    assert restored.snapshot(ident)[0]["action"] == "running"
    restored.close()


def test_limits_and_no_ack_on_failed_commit(tmp_path):
    journal = Journal(tmp_path / "audio.sqlite")
    journal.create("one", "room", "phone", "request", False)
    for seq, pcm in [(True, b"\0\0"), (-1, b"\0\0"), (0, b"1"), (0, b"0" * 24002)]:
        with pytest.raises(ValueError):
            journal.append("one", seq, pcm)
    assert journal.next_seq("one") == 0
    journal.db.execute("PRAGMA query_only=ON")
    with pytest.raises(sqlite3.OperationalError):
        journal.append("one", 0, b"\0\0")
    assert journal.next_seq("one") == 0
    journal.close()
