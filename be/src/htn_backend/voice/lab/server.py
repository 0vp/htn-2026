"""Loopback desktop microphone lab; no physical robot connection is created."""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from websockets.asyncio.client import connect

from ...simulation.service import ROOM
from ..prompts import LIVE_INSTRUCTIONS, LIVE_MODEL
from .backend import SimulationBackend
from .runtime import Delegator

ASSETS = Path(__file__).with_name("web")


def create_app(simulator="http://127.0.0.1:8794", memory_path="/tmp/htn-voice-lab.sqlite"):
    # Validate before exposing even read-only proxy routes.
    parsed = urlsplit(simulator)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("A loopback simulator is required")
    app = FastAPI()
    active = asyncio.Lock()

    @app.get("/")
    async def index():
        return FileResponse(ASSETS / "index.html")

    @app.get("/client.js")
    async def script():
        return FileResponse(ASSETS / "client.js", media_type="text/javascript")

    @app.get("/microphone.js")
    async def processor():
        return FileResponse(ASSETS / "microphone.js", media_type="text/javascript")

    @app.get("/camera.jpg")
    async def camera():
        async with httpx.AsyncClient(timeout=5) as client:
            health = await client.get(simulator + "/health")
            if health.json().get("execution_domain") != "simulation":
                return Response(status_code=409)
            image = await client.get(simulator + "/camera.jpg")
            return Response(
                image.content,
                image.status_code,
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store"},
            )

    @app.websocket("/voice")
    async def voice(browser: WebSocket):
        origin = urlsplit(browser.headers.get("origin", ""))
        if origin.scheme != "http" or origin.netloc != browser.headers.get("host"):
            await browser.close(code=1008)
            return
        await browser.accept()
        if active.locked():
            await browser.send_json({"kind": "error", "text": "Another voice test is active."})
            await browser.close(code=1008)
            return
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            await browser.send_json({"kind": "error", "text": "Server API key is missing."})
            await browser.close(code=1011)
            return
        async with active:
            loop = asyncio.get_running_loop()
            events = asyncio.Queue(maxsize=100)

            def record(event):
                if event.get("kind") not in {"delegation_result", "stop", "backend_error"}:
                    return

                def enqueue():
                    if not events.full():
                        events.put_nowait(event)

                loop.call_soon_threadsafe(enqueue)

            backend = SimulationBackend(simulator, ROOM, record, memory_path)
            runtime, session_id = None, None
            tasks = []
            try:
                await backend.start()
                async with connect(
                    "wss://api.openai.com/v1/live/sessions",
                    additional_headers={"Authorization": f"Bearer {key}"},
                    max_size=4_000_000,
                    open_timeout=20,
                ) as upstream:

                    async def send(event):
                        await upstream.send(json.dumps(event))

                    runtime = Delegator(backend, send, record)
                    await send(
                        {
                            "type": "session.start",
                            "session": {
                                "model": LIVE_MODEL,
                                "instructions": LIVE_INSTRUCTIONS,
                                "delegation": {"type": "client"},
                                "audio": {
                                    "format": {"type": "audio/pcm", "rate": 24000},
                                    "output": {"voice": "marin"},
                                },
                            },
                        }
                    )
                    started = json.loads(await asyncio.wait_for(upstream.recv(), 25))
                    if started.get("type") != "session.started":
                        raise RuntimeError("Live session could not start")
                    session_id = started["session"]["id"]
                    await browser.send_json({"kind": "ready"})

                    async def receive_browser():
                        while True:
                            message = await browser.receive()
                            if message["type"] == "websocket.disconnect":
                                return
                            if message.get("bytes") is not None:
                                pcm = message["bytes"]
                                if len(pcm) != 960:
                                    raise ValueError("Expected 20ms mono PCM16 at 24kHz")
                                await send(
                                    {
                                        "type": "session.input_audio.append",
                                        "audio": base64.b64encode(pcm).decode(),
                                    }
                                )
                            elif message.get("text") == "stop":
                                await runtime.stop_requested()
                            elif message.get("text") == "close":
                                return

                    async def receive_live():
                        async for raw in upstream:
                            event = json.loads(raw)
                            kind = event.get("type", "")
                            if kind == "session.output_audio.delta":
                                await browser.send_bytes(base64.b64decode(event["delta"]))
                            elif "transcript.delta" in kind:
                                await browser.send_json(
                                    {
                                        "kind": "transcript",
                                        "type": kind,
                                        "text": event.get("delta", ""),
                                    }
                                )
                            elif kind == "error":
                                raise RuntimeError("Live provider reported an error")
                            await runtime.handle(event)

                    async def report():
                        while True:
                            await browser.send_json(await events.get())

                    tasks = [
                        asyncio.create_task(fn()) for fn in (receive_browser, receive_live, report)
                    ]
                    done, _ = await asyncio.wait(
                        tasks, timeout=600, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        task.result()
                    await runtime.close()
                    await send({"type": "session.close"})
            except (WebSocketDisconnect, OSError):
                pass
            except Exception as error:
                try:
                    await browser.send_json({"kind": "error", "text": type(error).__name__})
                except Exception:
                    pass
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                for cleanup in ([runtime.close] if runtime else []) + [backend.close]:
                    try:
                        await cleanup()
                    except Exception:
                        pass
                if session_id:
                    try:
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.post(
                                f"https://api.openai.com/v1/live/sessions/{session_id}/hangup",
                                headers={"Authorization": f"Bearer {key}"},
                            )
                    except httpx.HTTPError:
                        pass
                try:
                    await browser.close()
                except RuntimeError:
                    pass

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8795)
    parser.add_argument("--simulator", default="http://127.0.0.1:8794")
    args = parser.parse_args()
    uvicorn.run(create_app(args.simulator), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
