"""Requests must never manufacture physical execution or change on retry."""

from concurrent.futures import ThreadPoolExecutor

from conftest import room

from htn_backend.processing.state import ProcessingState
from htn_backend.robotics.actions import Actions, SkillRequest
from htn_backend.robotics.scene import Scene
from htn_backend.storage.database import Store


def target(client, code):
    state = ProcessingState(client.app.state.store)
    state.publish(
        code,
        b"mesh",
        [{"object_id": "b", "label": "bottle", "evidence_digest": "abc"}],
        {},
        [],
        {"b": {"digest": "abc", "jpeg": b"image"}},
    )
    return state


def test_inspect_and_physical_actions_are_distinct(client):
    code = room(client)
    target(client, code)
    for skill in ("inspect", "navigate", "pick", "place", "stop"):
        response = client.post(
            f"/v1/rooms/{code}/actions",
            json={"request_id": skill, "skill": skill, "object_id": "b", "scene_revision": 1},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["state"] == ("completed" if skill == "inspect" else "blocked")
        assert result["dispatched"] is False and result["physical_success"] is False
        assert client.get(f"/v1/rooms/{code}/actions/{result['action_id']}").json() == result


def test_idempotency_survives_restart_and_concurrent_requests(client):
    code = room(client)
    state = target(client, code)
    actions = Actions(Scene(state))
    request = SkillRequest(request_id="same", skill="pick", object_id="b", scene_revision=1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: actions.submit(code, request), range(16)))
    assert len({r["action_id"] for r in results}) == 1
    second_store = Store(state.store.root)
    try:
        second = Actions(Scene(ProcessingState(second_store)))
        assert second.submit(code, request) == results[0]
    finally:
        second_store.close()
    response = client.post(
        f"/v1/rooms/{code}/actions", json={**request.model_dump(), "skill": "navigate"}
    )
    assert response.status_code == 409
    other = room(client)
    assert client.get(f"/v1/rooms/{other}/actions/{results[0]['action_id']}").status_code == 404


def test_stale_revision_missing_target_and_missing_evidence_block(client):
    code = room(client)
    state = target(client, code)
    state.publish(code, b"mesh", [{"object_id": "b", "label": "bottle"}], {}, [])
    for ident, revision in (("b", 1), ("missing", 2), ("b", 2)):
        result = client.post(
            f"/v1/rooms/{code}/actions",
            json={
                "request_id": f"{ident}-{revision}",
                "skill": "inspect",
                "object_id": ident,
                "scene_revision": revision,
            },
        ).json()
        assert result["state"] == "blocked" and result["result"] is None
    assert (
        client.post(
            f"/v1/rooms/{code}/actions",
            json={"request_id": "bad", "skill": "pick", "scene_revision": 2},
        ).status_code
        == 422
    )
