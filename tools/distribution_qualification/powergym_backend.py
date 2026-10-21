"""A deterministic numerical solve wrapper; original devices and ledger remain inherited."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "distribution_selection"))
from powergym_baselines.backend import SnapshotBackend  # noqa: E402


class QualificationBackend(SnapshotBackend):
    """Rebuild and initialize each PF so trial history cannot affect ledger rounding."""

    def __init__(
        self,
        case: dict,
        assets: Path,
        *,
        before_solve: Callable | None = None,
        failed_solve: Callable | None = None,
    ):
        self.before_solve = before_solve
        self.failed_solve = failed_solve
        super().__init__(case, assets)

    def _load_and_solve(self, step: int) -> None:
        if not 0 <= step < self.case["horizon"]:
            raise ValueError("power-flow query outside current episode")
        for index, name in enumerate(self.loads):
            self.circuit.Loads.Name = name
            multiplier = self.case["multipliers"][index][step]
            self.circuit.Loads.kW = self.nominal[index][0] * multiplier
            self.circuit.Loads.kvar = self.nominal[index][1] * multiplier
        self.solution.Tolerance = 1e-10
        self.solution.BuildYMatrix(2, True)
        self.engine.YMatrix.SolutionInitialized = False
        if self.before_solve is not None:
            self.before_solve()
        self.pf_calls += 1
        self.solution.Solve()
        if not self.solution.Converged:
            self.failed_pf_calls += 1
            if self.failed_solve is not None:
                self.failed_solve()
            raise ValueError("power flow did not converge")
