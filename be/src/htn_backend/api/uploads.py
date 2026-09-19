"""Bounded binary uploads with durable acknowledgements and retry-safe receipts."""

import io
import sqlite3

import anyio
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from ..capture.codec import MAX_FRAME_BYTES, decode
from ..storage.database import Store, StoreError
from .models import DeviceID, RoomID


def persist(store: Store, room_id: str, device_id: str, payload: bytes) -> dict:
    frame = decode(payload)
    if frame.rgb_jpeg:
        try:
            with Image.open(io.BytesIO(frame.rgb_jpeg)) as image:
                if image.format != "JPEG" or image.size != (
                    frame.header.rgb_width,
                    frame.header.rgb_height,
                ):
                    raise ValueError("JPEG dimensions disagree with frame header")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError("Invalid JPEG") from error
    return {
        **store.save(room_id, device_id, frame, payload),
        "frame_id": frame.header.frame_id,
        "session_id": frame.header.session_id,
        "epoch": frame.header.epoch,
        "room_id": room_id,
        "device_id": device_id,
    }


def router(store: Store) -> APIRouter:
    routes = APIRouter(prefix="/v1/rooms", tags=["frames"])
    uploads = anyio.CapacityLimiter(8)
    streams = anyio.CapacityLimiter(32)

    @routes.post("/{room_id}/devices/{device_id}/frames")
    async def upload(room_id: RoomID, device_id: DeviceID, request: Request) -> dict:
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            raise HTTPException(415, "Expected application/octet-stream")
        try:
            uploads.acquire_nowait()
        except anyio.WouldBlock as error:
            raise HTTPException(
                429, "Upload capacity reached; retry", headers={"Retry-After": "1"}
            ) from error
        try:
            await run_in_threadpool(store.member, room_id, device_id)
            body = bytearray()
            with anyio.fail_after(30):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_FRAME_BYTES:
                        raise HTTPException(413, "Frame exceeds size limit")
                    body.extend(chunk)
            return await run_in_threadpool(persist, store, room_id, device_id, bytes(body))
        except TimeoutError as error:
            raise HTTPException(408, "Upload timed out; retry the same frame") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        finally:
            uploads.release()

    @routes.websocket("/{room_id}/devices/{device_id}/stream")
    async def stream(room_id: RoomID, device_id: DeviceID, ws: WebSocket) -> None:
        try:
            streams.acquire_nowait()
        except anyio.WouldBlock:
            await ws.close(code=1013)
            return
        try:
            await ws.accept()
            await run_in_threadpool(store.member, room_id, device_id)
            while True:
                with anyio.fail_after(120):
                    message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                payload = message.get("bytes")
                if payload is None:
                    await ws.send_json({"error": "Expected a binary frame", "status": 422})
                    continue
                if len(payload) > MAX_FRAME_BYTES:
                    await ws.close(code=1009)
                    return
                # Wait without admitting another frame on this connection. The client
                # retains each unacknowledged frame and resends it after reconnecting.
                async with uploads:
                    try:
                        receipt = await run_in_threadpool(
                            persist, store, room_id, device_id, payload
                        )
                    except ValueError as error:
                        receipt = {"error": str(error), "status": 422}
                    except StoreError as error:
                        receipt = {"error": error.detail, "status": error.status}
                    except (OSError, sqlite3.Error):
                        receipt = {"error": "Storage unavailable; retry", "status": 503}
                await ws.send_json(receipt)
        except StoreError as error:
            await ws.send_json({"error": error.detail, "status": error.status})
            await ws.close(code=1008)
        except TimeoutError:
            await ws.close(code=1000, reason="Idle connection; reconnect to resume")
        except WebSocketDisconnect:
            pass
        finally:
            streams.release()

    return routes
