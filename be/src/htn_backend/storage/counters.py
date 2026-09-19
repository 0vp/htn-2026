"""Transactionally maintained lifetime counters avoid rescanning capture history."""


def initialize(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='room_counts'").fetchone():
        return
    db.execute(
        "CREATE TABLE room_counts (room_id TEXT PRIMARY KEY, received INTEGER NOT NULL, "
        "retained INTEGER NOT NULL, bytes INTEGER NOT NULL)"
    )
    db.execute(
        "INSERT INTO room_counts SELECT room_id, COUNT(*), "
        "SUM(length(payload)>0), SUM(length(payload)) FROM frames GROUP BY room_id"
    )
    db.execute("""CREATE TRIGGER count_capture AFTER INSERT ON frames BEGIN
        INSERT INTO room_counts VALUES(NEW.room_id,1,length(NEW.payload)>0,length(NEW.payload))
        ON CONFLICT(room_id) DO UPDATE SET received=received+1,
          retained=retained+(length(NEW.payload)>0), bytes=bytes+length(NEW.payload);
        END""")
    db.execute("""CREATE TRIGGER count_retention AFTER UPDATE OF payload ON frames BEGIN
        UPDATE room_counts SET bytes=bytes+length(NEW.payload)-length(OLD.payload),
          retained=retained+(length(NEW.payload)>0)-(length(OLD.payload)>0)
          WHERE room_id=NEW.room_id;
        END""")


def initialize_processing(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='processing_counts'").fetchone():
        return
    db.execute(
        "CREATE TABLE processing_counts (room_id TEXT NOT NULL,state TEXT NOT NULL, "
        "count INTEGER NOT NULL, PRIMARY KEY(room_id,state))"
    )
    db.execute(
        "INSERT INTO processing_counts SELECT f.room_id,p.state,COUNT(*) "
        "FROM processing p JOIN frames f ON p.sequence=f.sequence GROUP BY f.room_id,p.state"
    )
    db.execute("""CREATE TRIGGER count_processed AFTER INSERT ON processing BEGIN
        INSERT INTO processing_counts VALUES(
          (SELECT room_id FROM frames WHERE sequence=NEW.sequence),NEW.state,1)
        ON CONFLICT(room_id,state) DO UPDATE SET count=count+1;
        END""")
    db.execute("""CREATE TRIGGER count_reprocessed AFTER UPDATE OF state ON processing BEGIN
        UPDATE processing_counts SET count=count-1 WHERE state=OLD.state AND room_id=
          (SELECT room_id FROM frames WHERE sequence=OLD.sequence);
        INSERT INTO processing_counts VALUES(
          (SELECT room_id FROM frames WHERE sequence=NEW.sequence),NEW.state,1)
        ON CONFLICT(room_id,state) DO UPDATE SET count=count+1;
        END""")
