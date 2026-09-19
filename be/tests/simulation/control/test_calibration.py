import numpy as np

from htn_backend.simulation.control.calibration import OnlineJacobian


def test_secant_updates_reduce_error_on_unseen_directions():
    rng = np.random.default_rng(932)
    truth = np.array([[1.2, 0.3], [-0.2, 0.7]])
    model = OnlineJacobian(np.eye(2))
    initial = np.linalg.norm(model.matrix - truth)
    for _ in range(180):
        u = rng.uniform(-0.03, 0.03, 2)
        model.update(u, truth @ u + rng.normal(0, 0.00005, 2))
    assert np.linalg.norm(model.matrix - truth) < initial * 0.05
    assert model.report()["fully_excited"]
    goal = np.array([0.01, -0.008])
    assert np.linalg.norm(truth @ model.correction(goal) - goal) < 0.001


def test_discontinuities_and_missing_excitation_do_not_claim_calibration():
    model = OnlineJacobian(np.eye(2))
    model.update([0, 0], [0, 0])
    model.update([0.01, 0], [10, 0])
    model.update([float("nan"), 0], [0, 0])
    for _ in range(20):
        model.update([0.01, 0], [0.01, 0])
    assert model.rejected == 3
    assert not model.report()["fully_excited"]
    assert np.all(np.isfinite(model.matrix))
