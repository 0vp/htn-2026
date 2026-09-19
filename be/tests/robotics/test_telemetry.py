"""The teammate firmware contract never supplies measured joint pose or task success."""

from conftest import room


def sample():
    return dict(
        type="telemetry",
        packVolts=12.1,
        ampsEstimate=0.3,
        servoDeg=dict(shoulder=0, elbow=0, wrist=0),
        winchPos=[0, 0.5, 1],
        limits=[[False, False]] * 3,
        loopHz=100,
        uptimeS=12,
        heapKb=100,
    )


def test_telemetry_duplicate_old_sequences_and_freshness(client):
    code = room(client)
    body = dict(device_id="esp32-base", session_id="a" * 32, sequence=10, telemetry=sample())
    url = f"/v1/rooms/{code}/robot/telemetry"
    first = client.post(url, json=body).json()
    duplicate = client.post(url, json=body).json()
    assert duplicate["duplicate"] and first["received_at"] == duplicate["received_at"]
    assert client.post(url, json={**body, "sequence": 9}).status_code == 409
    assert (
        client.post(url, json={**body, "telemetry": {**sample(), "uptimeS": 13}}).status_code == 409
    )
    scene = client.get(f"/v1/rooms/{code}/scene").json()
    robot = scene["robot_reports"][0]
    assert robot["recently_received"] and robot["robot_pose"] is None
    assert not robot["navigation_calibrated"] and robot["physical_success"] is None
    assert not scene["capabilities"]["navigate"]
    db = client.app.state.store.db
    with db:
        db.execute("UPDATE robot_telemetry SET received_at=received_at-10")
    assert not client.get(f"/v1/rooms/{code}/scene").json()["robot_reports"][0]["recently_received"]
    assert client.post(url, json={**body, "session_id": "b" * 32, "sequence": 0}).status_code == 200


def test_telemetry_cannot_claim_physical_success_or_nan(client):
    code = room(client)
    body = dict(device_id="esp32-base", session_id="a" * 32, sequence=0, telemetry=sample())
    for change in ({"physical_success": True}, {"packVolts": "NaN"}, {"type": "command"}):
        assert (
            client.post(
                f"/v1/rooms/{code}/robot/telemetry",
                json={**body, "telemetry": {**sample(), **change}},
            ).status_code
            == 422
        )
