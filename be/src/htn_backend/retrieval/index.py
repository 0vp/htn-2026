"""Durable visual evidence retrieval; candidates never become object detections."""

import io
import threading
import time
from collections import OrderedDict

import numpy as np
from PIL import Image

from .model import MODEL_KEY


class EvidenceIndex:
    def __init__(self, store, encoder):
        self.store, self.encoder = store, encoder
        self.lock = threading.Lock()
        self.queries = OrderedDict()
        with store.lock, store.db:
            store.db.execute("""CREATE TABLE IF NOT EXISTS visual_embeddings (
                digest TEXT NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL,
                PRIMARY KEY(digest,model)
            )""")

    def search(self, room_id, query):
        started = time.perf_counter()
        # Bound concurrent GPU calls and memory without holding the room DB lock.
        if not self.lock.acquire(timeout=1):
            raise TimeoutError("Visual retrieval is busy")
        try:
            with self.store.lock:
                self.store.require_room(room_id)
                rows = self.store.db.execute(
                    "SELECT e.object_id,e.digest,e.jpeg,v.vector FROM object_evidence e "
                    "LEFT JOIN visual_embeddings v ON e.digest=v.digest AND v.model=? "
                    "WHERE e.room_id=? ORDER BY e.object_id LIMIT 512",
                    (MODEL_KEY, room_id),
                ).fetchall()
            missing = {r["digest"]: r["jpeg"] for r in rows if r["vector"] is None}
            vectors = {}
            keys = list(missing)
            for offset in range(0, len(keys), 8):
                batch = keys[offset : offset + 8]
                images = []
                for key in batch:
                    with Image.open(io.BytesIO(missing[key])) as image:
                        images.append(image.convert("RGB"))
                embedded = self.encoder.encode(images=images)
                if len(embedded) != len(batch):
                    raise ValueError("Encoder batch length mismatch")
                for key, vector in zip(batch, embedded, strict=True):
                    vectors[key] = vector
                with self.store.lock, self.store.db:
                    self.store.db.executemany(
                        "INSERT OR REPLACE INTO visual_embeddings VALUES(?,?,?)",
                        [
                            (key, MODEL_KEY, np.asarray(vector, dtype="<f4").tobytes())
                            for key, vector in zip(batch, embedded, strict=True)
                        ],
                    )
            if not rows:
                return dict(model=MODEL_KEY, candidates=[], indexed=0, elapsed_ms=0)
            if query not in self.queries:
                self.queries[query] = self.encoder.encode(text=[query])[0]
            self.queries.move_to_end(query)
            while len(self.queries) > 128:
                self.queries.popitem(last=False)
            text = self.queries[query]
            candidates = []
            for row in rows:
                vector = vectors.get(row["digest"])
                if vector is None:
                    vector = np.frombuffer(row["vector"], dtype="<f4")
                if vector.shape != text.shape or not np.isfinite(vector).all():
                    raise ValueError("Stored embedding is invalid")
                candidates.append(
                    dict(
                        object_id=row["object_id"],
                        evidence_digest=row["digest"],
                        cosine_similarity=float(vector @ text),
                    )
                )
            candidates.sort(key=lambda c: c["cosine_similarity"], reverse=True)
            with self.store.lock, self.store.db:
                # Evidence is replaced with every map; remove orphaned vectors automatically.
                self.store.db.execute(
                    "DELETE FROM visual_embeddings WHERE model<>? OR digest NOT IN "
                    "(SELECT digest FROM object_evidence)",
                    (MODEL_KEY,),
                )
            return dict(
                model=MODEL_KEY,
                candidates=candidates[:20],
                indexed=len(rows),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                score_meaning="cosine ranking, not probability or confirmed identification",
            )
        finally:
            self.lock.release()
