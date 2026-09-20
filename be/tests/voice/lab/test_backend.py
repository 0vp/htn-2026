import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from htn_backend.voice.lab.backend import AuditedTools, SimulationBackend
from htn_backend.voice.lab.memory import Memory


def test_local_physical_server_is_rejected(monkeypatch):
    factory = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "execution_domain": "physical",
                "room_id": "51A00001",
            },
        )
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: factory(transport=transport, **kwargs)
    )

    async def exercise():
        backend = SimulationBackend("http://127.0.0.1:8794", "51A00001")
        try:
            with pytest.raises(ValueError, match="not the expected simulation"):
                await backend.start()
            assert backend.server is None
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_cancel_gate_waits_for_inflight_request_and_blocks_later_actions():
    entered, release, disable_started = threading.Event(), threading.Event(), threading.Event()
    requests = []

    def receive(request):
        requests.append(request)
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json={"state": "running"})

    notes = Memory(":memory:", "51A00001")
    with httpx.Client(
        base_url="http://127.0.0.1", transport=httpx.MockTransport(receive)
    ) as client:
        tools = AuditedTools(client, "51A00001", lambda _: None, notes)
        action = {
            "skill": "navigate",
            "object_id": "table",
            "scene_revision": 1,
            "request_id": "one",
        }

        def disable():
            disable_started.set()
            tools.set_enabled(False)

        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(tools.call, "request_skill", action)
            assert entered.wait(1)
            cancelled = pool.submit(disable)
            assert disable_started.wait(1)
            assert not cancelled.done()
            release.set()
            assert first.result()["success"]
            cancelled.result()
        assert not tools.call("request_skill", {**action, "request_id": "two"})["success"]
        assert len(requests) == 1
    notes.close()
