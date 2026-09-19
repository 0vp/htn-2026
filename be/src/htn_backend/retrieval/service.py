"""Loopback-only retrieval service, separate from capture/mapping inference queues."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from ..api.models import RoomID
from ..processing.state import ProcessingState
from ..storage.database import Store, StoreError
from .index import EvidenceIndex
from .model import MODEL_KEY, Encoder


def application():
    store = Store(Path(os.environ.get("HTN_DATA_DIR", "data")))
    ProcessingState(store)
    index = EvidenceIndex(store, Encoder())

    @asynccontextmanager
    async def lifespan(app):
        yield
        store.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ready", "model": MODEL_KEY}

    @app.get("/search")
    def search(room_id: RoomID, q: str = Query(min_length=1, max_length=256)):
        try:
            return index.search(room_id, q)
        except StoreError as error:
            raise HTTPException(error.status, error.detail) from error
        except TimeoutError as error:
            raise HTTPException(503, str(error)) from error

    return app
