"""Small durable anchor records survive raw-frame retention."""

import json

from ..capture.geography import GeographicAnchor, improves


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS geographic_anchors (
        room_id TEXT, device_id TEXT, session_id TEXT, epoch INTEGER,
        sequence INTEGER, received_at REAL, anchor TEXT,
        PRIMARY KEY(room_id,device_id,session_id,epoch),
        FOREIGN KEY(room_id,device_id) REFERENCES devices(room_id,device_id))""")


def save(db, room, device, header, sequence, received):
    anchor = header.geographic_anchor
    if anchor is None:
        return
    identity = (room, device, header.session_id, header.epoch)
    old = db.execute(
        "SELECT anchor FROM geographic_anchors WHERE room_id=? AND device_id=? "
        "AND session_id=? AND epoch=?",
        identity,
    ).fetchone()
    if old and not improves(anchor, GeographicAnchor.model_validate_json(old[0])):
        return
    db.execute(
        "INSERT INTO geographic_anchors VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(room_id,device_id,session_id,epoch) DO UPDATE SET "
        "sequence=excluded.sequence,received_at=excluded.received_at,anchor=excluded.anchor",
        (*identity, sequence, received, anchor.model_dump_json(exclude_none=True)),
    )


def read(db, room):
    rows = db.execute(
        "SELECT * FROM geographic_anchors WHERE room_id=? ORDER BY sequence DESC", (room,)
    ).fetchall()
    return [
        {**{k: row[k] for k in row.keys() if k != "anchor"}, "anchor": json.loads(row["anchor"])}
        for row in rows
    ]


def response(db, room):
    return {
        "schema_version": 1,
        "approximate": True,
        "purpose": "outdoor_context_only",
        "coordinate_reference": "WGS84",
        "local_coordinates": "unchanged_metres",
        "warning": "Indoor GPS and compass may be inaccurate. Not navigation or alignment.",
        "anchors": read(db, room),
    }
