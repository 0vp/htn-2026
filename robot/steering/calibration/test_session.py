import io
import json

from session import run
from test_pulse import Device


def test_multiple_requests_use_same_connection_and_end_disarmed():
    device = Device()
    output = io.StringIO()
    run(device, ['{"duty":0,"steering_deg":1,"seconds":0.02}\n'] * 2, output)
    results = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(results) == 2
    assert all(result["reported_stop"] for result in results)
    assert not device.supervised
    assert device.duty == 0


def test_invalid_request_ends_session_without_replaying_following_command():
    device = Device()
    output = io.StringIO()
    run(device, ["bad json", '{"duty":0.1,"steering_deg":0,"seconds":0.02}'], output)
    assert len(output.getvalue().splitlines()) == 1
    assert not any(value.get("armed") for value in device.sent)
