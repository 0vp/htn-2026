"""iPhone voice signaling contract."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..api.models import DeviceID, RoomID


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: DeviceID
    sdp: str = Field(min_length=10, max_length=65536)
    codex_enabled: bool = True
    request_id: str = Field(min_length=1, max_length=80)


class End(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: DeviceID
    session_id: str = Field(min_length=1, max_length=200)


def router(service):
    routes = APIRouter(prefix="/v1/rooms/{room_id}/voice", tags=["voice"])

    @routes.get("/capabilities")
    async def capabilities(room_id: RoomID, device_id: DeviceID):
        return service.capabilities(room_id, device_id)

    @routes.post("/sessions", status_code=201)
    async def create(room_id: RoomID, data: Offer):
        return await service.create(room_id, data)

    @routes.post("/end")
    async def end(room_id: RoomID, data: End):
        service.authorize(room_id, data.device_id, allow_closed=True)
        call = service.calls.get(data.session_id)
        if call and (call.room != room_id or call.device != data.device_id):
            raise HTTPException(403, "Voice session belongs to another room")
        await service.end(data.session_id)
        return {"ended": True}

    return routes
