"""WebSocket relay so the cloud agent can drive a base that sits behind a laptop's NAT.

  base side        robot/scripts/drive.py dials  /v1/rooms/{room}/robot/base?token=...
  controller side  the agent's RobotLink dials   /v1/rooms/{room}/robot/controller/?token=...

Command packets flow controller -> base and telemetry flows base -> controller, verbatim. Both
sides need HTN_ROBOT_TOKEN; without it configured the relay refuses everyone. When either side
drops, the other is closed so the base's command lease and firmware watchdog stop the motors.
"""

import asyncio
import hmac
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..api.models import RoomID

MAX_MESSAGE = 8192


class Relay:
    def __init__(self):
        self.sockets: dict[tuple[str, str], WebSocket] = {}

    @staticmethod
    def allowed(token: str) -> bool:
        secret = os.environ.get("HTN_ROBOT_TOKEN", "")
        return bool(secret) and hmac.compare_digest(token.encode(), secret.encode())

    async def serve(self, socket: WebSocket, room_id: str, role: str, token: str) -> None:
        peer_role = "controller" if role == "base" else "base"
        if not self.allowed(token):
            await socket.close(code=1008, reason="Robot token required")
            return
        await socket.accept()
        previous = self.sockets.pop((room_id, role), None)
        if previous is not None:  # Newest connection wins; a stale one may be half-open.
            await self._close(previous, "Replaced by a newer connection")
        self.sockets[(room_id, role)] = socket
        try:
            while True:
                message = await socket.receive_text()
                peer = self.sockets.get((room_id, peer_role))
                if peer is not None and len(message) <= MAX_MESSAGE:
                    try:
                        await peer.send_text(message)
                    except (RuntimeError, WebSocketDisconnect):
                        self.sockets.pop((room_id, peer_role), None)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if self.sockets.get((room_id, role)) is socket:
                del self.sockets[(room_id, role)]
                if role == "controller":
                    # The base must not keep a command from a controller that vanished.
                    base = self.sockets.get((room_id, "base"))
                    if base is not None:
                        stop = '{"type":"command","armed":false,"estop":false}'
                        await asyncio.gather(base.send_text(stop), return_exceptions=True)

    @staticmethod
    async def _close(socket: WebSocket, reason: str) -> None:
        try:
            await socket.close(code=1012, reason=reason)
        except RuntimeError:
            pass


def router() -> APIRouter:
    routes = APIRouter(prefix="/v1/rooms", tags=["robotics"])
    relay = Relay()

    @routes.websocket("/{room_id}/robot/base")
    async def base(socket: WebSocket, room_id: RoomID, token: str = ""):
        await relay.serve(socket, room_id, "base", token)

    @routes.websocket("/{room_id}/robot/controller/")
    async def controller(socket: WebSocket, room_id: RoomID, token: str = ""):
        await relay.serve(socket, room_id, "controller", token)

    return routes
