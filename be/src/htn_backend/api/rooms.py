"""Explicit room membership and bounded capture manifests."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from ..storage.database import Store
from .models import CreateRoom, JoinRoom, RoomID


def router(store: Store) -> APIRouter:
    routes = APIRouter(prefix="/v1/rooms", tags=["rooms"])

    @routes.get("")
    def list_rooms() -> dict:
        return {"rooms": store.rooms()}

    @routes.post("", status_code=201)
    def create_room(data: CreateRoom) -> dict:
        return store.create(data.name, data.device_id)

    @routes.get("/{room_id}")
    def get_room(room_id: RoomID) -> dict:
        return store.room(room_id)

    @routes.get("/{room_id}/geography")
    def geography(room_id: RoomID) -> dict:
        return store.room(room_id)["geography"]

    @routes.post("/{room_id}/join")
    def join_room(room_id: RoomID, data: JoinRoom) -> dict:
        return store.join(room_id, data.device_id, data.name)

    @routes.post("/{room_id}/close")
    def close_room(room_id: RoomID) -> dict:
        return store.close_room(room_id)

    @routes.post("/{room_id}/reset")
    def reset_room(room_id: RoomID) -> dict:
        return store.reset_room(room_id)

    @routes.get("/{room_id}/frames")
    def list_frames(
        room_id: RoomID,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict:
        rows = store.frames(room_id, after, limit)
        return {"frames": rows, "next_after": rows[-1]["sequence"] if rows else after}

    @routes.get(
        "/{room_id}/frames/{sequence}",
        responses={410: {"description": "Raw capture cleaned; its durable map remains available"}},
    )
    def get_frame(room_id: RoomID, sequence: int) -> Response:
        return Response(store.payload(room_id, sequence), media_type="application/octet-stream")

    return routes
