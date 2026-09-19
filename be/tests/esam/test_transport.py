"""Exercise a real subprocess pipe, including failure and bounded packet handling."""

import sys

import pytest

from htn_backend.perception.esam.client import EsamClient

from .test_instances import scene


def command(body):
    return [sys.executable, "-c", body]


def test_worker_exit_is_sticky_and_does_not_publish_objects():
    frame, detections, _ = scene()
    client = EsamClient(command("raise SystemExit(1)"))
    with pytest.raises(RuntimeError, match="exited"):
        client.integrate(frame, detections)
    assert client.process is None
    assert not client.catalog.tracks
    with pytest.raises(RuntimeError, match="failed"):
        client.integrate(frame, detections)


def test_oversized_response_is_rejected_before_allocation():
    frame, detections, _ = scene()
    client = EsamClient(
        command(
            "import sys,struct,time; sys.stdin.buffer.read(4); "
            "sys.stdout.buffer.write(struct.pack('<I', 64000001)); "
            "sys.stdout.buffer.flush(); time.sleep(1)"
        )
    )
    with pytest.raises(ValueError, match="memory bound"):
        client.integrate(frame, detections)
    assert client.process is None


def test_empty_valid_response_round_trip():
    frame, detections, _ = scene()
    client = EsamClient(
        command("""
import sys, struct, io
import numpy as np
n = struct.unpack('<I', sys.stdin.buffer.read(4))[0]
packet = sys.stdin.buffer.read(n)
with np.load(io.BytesIO(packet), allow_pickle=False) as request:
    assert request['depth_mm'][0, 0] == 2000
    assert request['reset'].item() is True
output = io.BytesIO()
np.savez(output, points=np.empty((0, 3)), offsets=np.array([0]),
         scores=np.empty(0), elapsed_ms=np.array(42), window_frames=np.array(1))
raw = output.getvalue()
sys.stdout.buffer.write(struct.pack('<I', len(raw)) + raw)
sys.stdout.buffer.flush()
""")
    )
    try:
        objects, surfaces, timing = client.integrate(frame, detections, reset_window=True)
        assert (objects, surfaces) == ([], {})
        assert timing == {"esam_ms": 42.0, "window_frames": 1}
    finally:
        client.close()
