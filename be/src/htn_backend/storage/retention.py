"""Reclaim only captures already represented by a committed cumulative checkpoint."""

import time

RAW_HISTORY_SECONDS = 600
RAW_TARGET_BYTES = 512_000_000


def cleanup(store, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with store.lock, store.db:
        size = store.db.execute("SELECT bytes FROM totals WHERE id=1").fetchone()[0]
        # Unmapped and active-segment captures are deliberately ineligible even under pressure.
        rows = store.db.execute(
            "SELECT sequence,length(payload) AS size FROM frames "
            "WHERE archived=1 AND length(payload)>0 AND (received_at<? OR ? > ?) "
            "ORDER BY sequence LIMIT 128",
            (now - RAW_HISTORY_SECONDS, size, RAW_TARGET_BYTES),
        ).fetchall()
        reclaimed = sum(r["size"] for r in rows)
        store.db.executemany(
            "UPDATE frames SET payload=X'' WHERE sequence=?", [(r["sequence"],) for r in rows]
        )
        store.db.execute("UPDATE totals SET bytes=MAX(0,bytes-?) WHERE id=1", (reclaimed,))
    # SQLite reuses freed pages. Incremental vacuum also releases pages for new databases.
    with store.lock:
        store.db.execute("PRAGMA incremental_vacuum(256)")
    return {"frames_cleaned": len(rows), "bytes_reclaimed": reclaimed}
