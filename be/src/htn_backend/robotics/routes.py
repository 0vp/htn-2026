"""Room-scoped observation and skill contracts for robot agents."""

from fastapi import APIRouter, Query, Request, Response

from ..api.models import DeviceID, RoomID
from ..retrieval.client import search as retrieve
from .actions import Actions, SkillRequest
from .scene import Scene
from .telemetry import Report


def router(state):
    routes = APIRouter(prefix="/v1/rooms", tags=["robotics"])
    scene = Scene(state)
    actions = Actions(scene)

    @routes.post("/{room_id}/robot/telemetry")
    def telemetry(room_id: RoomID, body: Report):
        return scene.robot_state.publish(room_id, body)

    @routes.get("/{room_id}/scene")
    def read_scene(room_id: RoomID):
        return scene.read(room_id)

    @routes.get("/{room_id}/scene/search")
    def search(room_id: RoomID, q: str = Query(min_length=1, max_length=256)):
        return retrieve(scene, room_id, q)

    @routes.get("/{room_id}/observations/latest")
    def observe(room_id: RoomID, device_id: DeviceID | None = None):
        return scene.observations.latest(room_id, device_id)

    @routes.get("/{room_id}/observations/{sequence}/image.jpg")
    def image(room_id: RoomID, sequence: int, request: Request):
        data, digest = scene.observations.image(room_id, sequence)
        headers = {"ETag": f'"{digest}"', "Cache-Control": "private, max-age=60"}
        if request.headers.get("if-none-match") == headers["ETag"]:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type="image/jpeg", headers=headers)

    @routes.post("/{room_id}/actions")
    def submit(room_id: RoomID, body: SkillRequest):
        return actions.submit(room_id, body)

    @routes.get("/{room_id}/actions/{action_id}")
    def receipt(room_id: RoomID, action_id: str):
        return actions.get(room_id, action_id)

    return routes
