"""Room and capture API."""

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.mapping import router as mapping_router
from .api.rooms import router as rooms_router
from .api.uploads import router as uploads_router
from .capture.codec import MAX_FRAME_BYTES
from .processing.state import ProcessingState
from .robotics.routes import router as robotics_router
from .storage.database import Store, StoreError
from .storage.retention import RAW_HISTORY_SECONDS, RAW_TARGET_BYTES
from .voice.reliable.routes import ReliableVoice
from .voice.reliable.routes import router as reliable_router
from .voice.routes import router as voice_router
from .voice.service import VoiceService


def create_app(data_dir: Path | None = None) -> FastAPI:
    store = Store(data_dir or Path(os.environ.get("HTN_DATA_DIR", "data")))

    processing = ProcessingState(store)
    voice = VoiceService(store)
    reliable = ReliableVoice(
        voice, (data_dir or Path(os.environ.get("HTN_DATA_DIR", "data"))) / "voice-audio.sqlite"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await reliable.close()
        await voice.close()
        store.close()

    app = FastAPI(title="HTN API", version="0.4.0", lifespan=lifespan)
    app.state.store = store
    app.state.voice = voice
    app.state.reliable_voice = reliable

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
            "version": "0.4.0",
            "storage": "durable",
            "processing": processing.worker(),
            "protocols": ["R3D1", "R3Z1", "R3S1"],
            "max_frame_bytes": MAX_FRAME_BYTES,
            "mapping_frame_limit": None,
            "retention": {
                "raw_history_seconds": RAW_HISTORY_SECONDS,
                "raw_pressure_target_bytes": RAW_TARGET_BYTES,
                "requires_committed_checkpoint": True,
                "preserves_sparse_alignment_references": True,
            },
        }

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "If-None-Match"],
        expose_headers=["ETag"],
    )
    app.include_router(voice_router(voice))
    app.include_router(reliable_router(reliable))
    app.include_router(mapping_router(processing))
    app.include_router(robotics_router(processing))
    app.include_router(rooms_router(store))
    app.include_router(uploads_router(store))
    return app
