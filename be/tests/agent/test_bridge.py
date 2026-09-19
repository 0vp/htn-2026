"""Exercise an actual WebSocket peer and HTTP receiver without connecting hardware."""

import asyncio
import json

from websockets.asyncio.server import serve

from htn_backend.agent import bridge as module


def test_bridge_never_sends_an_armed_command(monkeypatch):
    reports, sent = [], []
    sample = dict(
        type="telemetry",
        packVolts=12,
        ampsEstimate=0.3,
        servoDeg=dict(shoulder=0, elbow=0, wrist=0),
        winchPos=[0, 0, 0],
        limits=[[False, False]] * 3,
        loopHz=100,
        uptimeS=1,
        heapKb=100,
    )

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, path, json):
            reports.append((path, json))
            return self

        def raise_for_status(self):
            pass

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)

    async def peer(socket):
        sent.append(json.loads(await socket.recv()))
        await socket.send(json.dumps(sample))
        await asyncio.sleep(0.05)
        await socket.close()

    async def exercise():
        async with serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            await module.bridge("ABCDEF12", f"ws://127.0.0.1:{port}", "http://test")

    asyncio.run(exercise())
    assert sent == [{"type": "observerHeartbeat"}]
    assert reports[0][0] == "/v1/rooms/ABCDEF12/robot/telemetry"
    assert reports[0][1]["telemetry"]["servoDeg"]["elbow"] == 0
