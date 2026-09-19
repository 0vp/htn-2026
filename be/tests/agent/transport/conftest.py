"""Shared fixture: the real robot/steering protocol and watchdog, compiled for the host."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def firmware(tmp_path):
    root = Path(__file__).resolve().parents[4] / "robot/steering"
    include = root / ".pio/libdeps/steering/ArduinoJson/src"
    if not shutil.which("c++") or not include.exists():
        pytest.skip("Build robot/steering with PlatformIO to install the firmware headers")
    binary = tmp_path / "serial-fixture"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(include),
            str(root / "test/serial_fixture.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    class Device:
        def write(self, payload):
            process.stdin.write(payload)
            process.stdin.flush()

        def read_until(self, delimiter, maximum):
            return process.stdout.readline(maximum)

    yield Device()
    process.terminate()
    process.wait(timeout=3)
    process.stdin.close()
    process.stdout.close()
