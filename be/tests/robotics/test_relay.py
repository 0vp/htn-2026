"""The relay pipes commands to the base and telemetry back, and refuses missing tokens."""

import asyncio
import socket
import threading

import pytest
import uvicorn
import websockets
from fastapi import FastAPI

from htn_backend.robotics.relay import router


@pytest.fixture
def relay(monkeypatch):
    monkeypatch.setenv("HTN_ROBOT_TOKEN", "secret")
    app = FastAPI()
    app.include_router(router())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        pass
    yield f"ws://127.0.0.1:{port}/v1/rooms/A0000001/robot"
    server.should_exit = True
    thread.join(timeout=5)


def test_relay_pipes_both_ways_and_stops_base_when_controller_leaves(relay):
    async def scenario():
        async with websockets.connect(f"{relay}/base?token=secret") as base:
            async with websockets.connect(f"{relay}/controller/?token=secret") as controller:
                await asyncio.sleep(0.1)
                await controller.send('{"type":"command","armed":true}')
                assert await base.recv() == '{"type":"command","armed":true}'
                await base.send('{"type":"telemetry"}')
                assert await controller.recv() == '{"type":"telemetry"}'
            assert '"armed":false' in await asyncio.wait_for(base.recv(), 3)

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_relay_refuses_a_wrong_token(relay):
    async def scenario():
        with pytest.raises(websockets.WebSocketException):
            async with websockets.connect(f"{relay}/base?token=wrong") as base:
                await base.recv()

    asyncio.run(asyncio.wait_for(scenario(), 10))
