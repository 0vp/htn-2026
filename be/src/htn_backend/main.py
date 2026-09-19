"""Room and capture API."""

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.rooms import router as rooms_router
from .api.uploads import router as uploads_router
from .capture.codec import MAX_FRAME_BYTES
from .storage.database import Store, StoreError


def create_app(data_dir: Path | None = None) -> FastAPI:
    store = Store(data_dir or Path(os.environ.get("HTN_DATA_DIR", "data")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        store.close()

    app = FastAPI(title="HTN API", version="0.2.0", lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(StoreError)
    async def store_error(request: Request, error: StoreError) -> JSONResponse:
        return JSONResponse({"detail": error.detail}, status_code=error.status)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "Storage unavailable; retry"}, status_code=503)

    @app.get("/health")
    def health() -> dict:
        with store.lock:
            store.db.execute("SELECT 1").fetchone()
        return {
            "status": "ok",
            "service": "htn-backend",
            "version": "0.2.0",
            "storage": "durable",
            "processing": "not_running",
            "protocols": ["R3D1", "R3Z1", "R3S1"],
            "max_frame_bytes": MAX_FRAME_BYTES,
        }

    app.include_router(rooms_router(store))
    app.include_router(uploads_router(store))
    return app
