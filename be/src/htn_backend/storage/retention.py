"""Reclaim only captures already represented by a committed cumulative checkpoint."""

import time

RAW_HISTORY_SECONDS = 600
RAW_TARGET_BYTES = 512_000_000
PRESSURE_BYTES = 2_500_000_000  # Of the store's 4 GB cap.


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
        if not rows and size > PRESSURE_BYTES:
            # Safety valve: captures that never map (a session that cannot be aligned) would
            # otherwise fill the store and block every upload. Drop the oldest, keep recent ones.
            rows = store.db.execute(
                "SELECT sequence,length(payload) AS size FROM frames "
                "WHERE length(payload)>0 AND received_at<? ORDER BY sequence LIMIT 256",
                (now - RAW_HISTORY_SECONDS,),
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
