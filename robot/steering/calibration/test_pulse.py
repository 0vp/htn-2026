import json

import pytest
from pulse import pulse


class Device:
    def __init__(self, estop=False, stopped=True):
        self.sent = []
        self.estop = estop
        self.stopped = stopped
        self.supervised = False
        self.duty = 0

    def write(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        if value["type"] == "supervise":
            self.supervised = value["enabled"]
        elif value["type"] == "command":
            self.duty = value.get("drive", {}).get("duty", 0) if value["armed"] else 0

    def readline(self):
        return json.dumps(
            {
                "drivetrain": "single_steer_v1",
                "motor_duty": self.duty,
                "control": {"estop": self.estop, "supervised": self.supervised},
            }
        ).encode()


@pytest.mark.parametrize(
    "duty,steering,seconds",
    [(1, 0, 0.1), (0, 11, 0.1), (0, 0, 1), (float("nan"), 0, 0.1)],
)
def test_rejects_excessive_or_invalid_command(duty, steering, seconds):
    device = Device()
    with pytest.raises(ValueError):
        pulse(device, duty, steering, seconds)
    assert device.sent == []


def test_pulse_reports_stop_and_disarms():
    device = Device()
    result = pulse(device, 0.1, 5, 0.02)
    assert result["reported_stop"]
    assert not result["physical_stop_verified"]
    assert any(v.get("armed") for v in device.sent)
    assert device.sent[-1] == {"type": "supervise", "enabled": False}
    assert device.duty == 0


def test_estop_never_arms():
    device = Device(estop=True)
    with pytest.raises(RuntimeError, match="Emergency"):
        pulse(device, 0.1, 0, 0.02)
    assert not any(v.get("armed") for v in device.sent)
    assert not device.supervised


def test_disconnect_preserves_evidence_without_claiming_stop():
    import serial

    class DisconnectingDevice(Device):
        def write(self, raw):
            if len(self.sent) >= 3:
                raise serial.SerialException("link lost")
            super().write(raw)

    result = pulse(DisconnectingDevice(), 0, 5, 0.02)
    assert result["error"] == "link lost"
    assert result["samples"]
    assert not result["reported_stop"]
    assert not result["physical_stop_verified"]
