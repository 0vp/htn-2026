"""The learned motion rates cannot run away from the floor calibration."""

import json
from types import SimpleNamespace

from htn_backend.agent.embodied import navigator as nav


def make(tmp_path, monkeypatch, saved=None):
    rates = tmp_path / "rates.json"
    if saved:
        rates.write_text(json.dumps(saved))
    monkeypatch.setattr(nav, "RATES_FILE", rates)
    return nav.Navigator(SimpleNamespace(), SimpleNamespace())


def test_poisoned_rates_file_is_ignored(tmp_path, monkeypatch):
    # The values a feedback loop once wrote: 16 deg/s made every turn three times too long.
    robot = make(tmp_path, monkeypatch, {"turn": 16.2, "forward": 0.148})
    assert robot.rates == nav.DEFAULT_RATES


def test_learning_moves_slowly_and_stays_in_bounds(tmp_path, monkeypatch):
    robot = make(tmp_path, monkeypatch)
    for _ in range(50):
        robot._learn("turn", 5.0)  # Absurdly slow measurements, e.g. a wrapped angle.
    low, high = nav.RATE_LIMITS["turn"]
    assert low <= robot.rates["turn"] <= high
    before = robot.rates["forward"]
    robot._learn("forward", 0.5)
    assert abs(robot.rates["forward"] - before) < 0.06  # One sample only nudges it.
