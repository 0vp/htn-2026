"""Bounded online secant calibration from measured input/output displacements."""

import numpy as np


class OnlineJacobian:
    def __init__(self, prior):
        self.matrix = np.asarray(prior, dtype=float).copy()
        self.samples = 0
        self.rejected = 0
        self.residual = 0.0
        self.excitation = np.zeros((self.matrix.shape[1], self.matrix.shape[1]))

    def update(self, displacement, response):
        u, y = np.asarray(displacement), np.asarray(response)
        norm = float(u @ u)
        if not np.all(np.isfinite(u)) or not np.all(np.isfinite(y)) or norm < 1e-8:
            self.rejected += 1
            return
        residual = y - self.matrix @ u
        # Reject discontinuities, contacts and gross tracking jumps as calibration samples.
        if np.linalg.norm(residual) > 0.08:
            self.rejected += 1
            return
        candidate = self.matrix + 0.25 * np.outer(residual, u) / (norm + 1e-5)
        if np.linalg.norm(candidate) > 12:
            self.rejected += 1
            return
        self.matrix = candidate
        self.samples += 1
        self.excitation += np.outer(u, u)
        self.residual = 0.9 * self.residual + 0.1 * float(np.linalg.norm(residual))

    def correction(self, error, damping=0.03):
        j = self.matrix
        return j.T @ np.linalg.solve(j @ j.T + damping**2 * np.eye(j.shape[0]), error)

    def report(self):
        eigenvalues = np.linalg.eigvalsh(self.excitation)
        return dict(
            method="damped_Broyden_secant",
            accepted_samples=self.samples,
            rejected_samples=self.rejected,
            residual_ema=self.residual,
            excitation_min=float(eigenvalues[0]),
            fully_excited=bool(eigenvalues[0] > 1e-5),
        )
