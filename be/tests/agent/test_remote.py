"""Voice turns go to a polling laptop worker and its answer comes back."""

import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from htn_backend.agent import remote


def test_worker_claims_a_turn_and_returns_the_result():
    async def scenario():
        hub = remote.Hub()
        assert not hub.present()
        polling = asyncio.create_task(hub.claim())
        await asyncio.sleep(0)
        assert hub.present()
        turn = asyncio.create_task(hub.execute("A0000001", "go forward"))
        job = await polling
        assert (job["room_id"], job["prompt"]) == ("A0000001", "go forward")
        assert hub.finish(job["job_id"], "moved")
        assert await turn == "moved"
        assert not hub.finish(job["job_id"], "again")

    asyncio.run(scenario())


def test_worker_routes_need_the_token(monkeypatch):
    monkeypatch.setenv("HTN_ROBOT_TOKEN", "secret")
    app = FastAPI()
    app.include_router(remote.router())
    client = TestClient(app)
    assert client.post("/v1/agent/jobs/claim").status_code == 403
    bad = client.post(
        "/v1/agent/jobs/x/result", json={"result": "r"}, headers={"Authorization": "Bearer no"}
    )
    assert bad.status_code == 403
    good = {"Authorization": "Bearer secret"}
    assert (
        client.post("/v1/agent/jobs/x/result", json={"result": "r"}, headers=good).status_code
        == 404
    )
    with pytest.raises(HTTPException):
        remote.authorize(None)
