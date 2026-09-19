"""Simulation commands must never inherit the physical robot connection."""

import sys

import pytest

pytest.importorskip("mujoco")

from htn_backend.simulation import run as cli


def test_simulation_runner_excludes_hardware_even_when_host_has_robot_credentials(monkeypatch):
    calls = []

    class Health:
        def raise_for_status(self):
            pass

        def json(self):
            return {"execution_domain": "simulation"}

    async def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setenv("HTN_ROBOT_URL", "ws://192.168.4.1:81")
    monkeypatch.setenv("HTN_ROBOT_TOKEN", "test-only")
    monkeypatch.setattr(sys, "argv", ["simulation", "--command", "stop"])
    monkeypatch.setattr(cli.httpx, "get", lambda *a, **kw: Health())
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/test/codex")
    monkeypatch.setattr(cli, "run", fake_run)
    cli.main()
    assert calls[0][1] == {"motion": None}
    assert calls[0][0][2] == "http://127.0.0.1:8792"


def test_simulation_runner_rejects_a_non_simulator_endpoint(monkeypatch):
    class Health:
        def raise_for_status(self):
            pass

        def json(self):
            return {"service": "htn-backend"}

    monkeypatch.setattr(sys, "argv", ["simulation", "--command", "drive"])
    monkeypatch.setattr(cli.httpx, "get", lambda *a, **kw: Health())
    with pytest.raises(SystemExit):
        cli.main()
