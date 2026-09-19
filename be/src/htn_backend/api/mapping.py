"""Live room map contracts independent of the dashboard implementation."""

import asyncio
import json

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..processing.state import ProcessingState
from .models import RoomID


def router(state: ProcessingState) -> APIRouter:
    routes = APIRouter(prefix="/v1/rooms", tags=["mapping"])

    @routes.get("/{room_id}/processing")
    def status(room_id: RoomID) -> dict:
        return {**state.status(room_id), "alignments": state.transforms(room_id)}

    @routes.get("/{room_id}/map")
    def room_map(room_id: RoomID) -> dict:
        return state.snapshot(room_id, include_mesh=False)

    @routes.get("/{room_id}/mesh.glb")
    def mesh(room_id: RoomID, request: Request) -> Response:
        row = state.snapshot(room_id)
        etag = f'"{room_id}-{row["revision"]}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return Response(
            row["mesh"],
            media_type="model/gltf-binary",
            headers={"ETag": etag, "Cache-Control": "no-cache"},
        )

    @routes.get("/{room_id}/objects")
    def objects(room_id: RoomID, q: str = Query(default="", max_length=256)) -> dict:
        if q.strip():
            return {"objects": state.search(room_id, q), "search": "sqlite_fts5"}
        row = state.snapshot(room_id, include_mesh=False)
        return {"revision": row["revision"], "objects": row["objects"]}

    @routes.get("/{room_id}/objects/{object_id}/evidence.jpg")
    def evidence(room_id: RoomID, object_id: str) -> Response:
        row = state.evidence(room_id, object_id)
        return Response(
            row["jpeg"],
            media_type="image/jpeg",
            headers={"ETag": '"' + row["digest"] + '"', "Cache-Control": "no-cache"},
        )

    @routes.get("/{room_id}/events")
    async def events(room_id: RoomID, request: Request) -> StreamingResponse:
        state.store.room(room_id)

        async def stream():
            previous = None
            while not await request.is_disconnected():
                payload = await asyncio.to_thread(state.status, room_id)
                encoded = json.dumps(payload, separators=(",", ":"))
                if encoded != previous:
                    yield f"event: processing\ndata: {encoded}\n\n"
                    previous = encoded
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return routes
