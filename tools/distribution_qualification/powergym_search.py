"""Full-grid device searches and energy-neutral, explicitly privileged references."""

from __future__ import annotations

import copy
import itertools
import math
import sys
import time
from pathlib import Path

SELECTION = Path(__file__).resolve().parents[1] / "distribution_selection"
sys.path.insert(0, str(SELECTION))
from powergym_backend import QualificationBackend  # noqa: E402
from powergym_selection import summarize  # noqa: E402


def objective(violation: float, loss_kwh: float, movements: int) -> tuple[float, float]:
    """Safety first; the unchanged canary loss/operation cost breaks ties."""
    return round(violation, 10), loss_kwh / 1000 + movements / 33


def terminal_valid(initial: list, final: list, steps: int, tolerance: float) -> bool:
    return (
        steps == 24
        and len(initial) == len(final)
        and all(math.isfinite(e) and abs(e - i) <= tolerance for i, e in zip(initial, final))
    )


def paired_schedules(
    schedule: list[list[int]], battery_index: int, slots: list[int], amplitudes: list[int]
):
    """Discharge before charging, preserving all other device/battery commands.

    Equal command quanta do not certify equal actual energy. Every candidate
    still passes the original rounded terminal-power ledger before acceptance.
    """
    for first, last in itertools.combinations(slots, 2):
        for amount in amplitudes:
            if schedule[first][battery_index] + amount > 32 or (
                schedule[last][battery_index] - amount < 0
            ):
                continue
            candidate = copy.deepcopy(schedule)
            candidate[first][battery_index] += amount
            candidate[last][battery_index] -= amount
            yield candidate


class DayEvaluator:
    """Reusable isolated DSS context; queries never advance committed state."""

    def __init__(
        self,
        case: dict,
        assets: Path,
        *,
        max_pf_calls: int = 200000,
        max_wall_seconds: float = 1800,
    ):
        self.case, self.assets = case, assets
        self.started = time.monotonic()
        self.max_pf_calls, self.max_wall_seconds = max_pf_calls, max_wall_seconds
        self.backend = QualificationBackend(case, assets)
        self.caps = len(self.backend.capacitors)
        self.devices = self.caps + len(self.backend.regulators)
        self.initial_action = (
            [1] * self.caps + [32] * (self.devices - self.caps) + [16] * len(self.backend.batteries)
        )
        self.cache: dict[tuple, dict] = {}
        self.replay_pf_calls = 0
        self.replay_failed_pf_calls = 0
        self.auxiliary_pf_calls = 0
        self.auxiliary_failed_pf_calls = 0
        self.cache_hits = 0
        self.query_requests = 0
        self.last_query: dict | None = None

    def diagnostics(self) -> dict:
        return {
            "case_cumulative_pf_calls": self.pf_calls,
            "case_cumulative_wall_seconds": time.monotonic() - self.started,
            "query_requests": self.query_requests,
            "cache_hits": self.cache_hits,
            "failed_pf_calls": (
                self.backend.failed_pf_calls
                + self.replay_failed_pf_calls
                + self.auxiliary_failed_pf_calls
            ),
            "last_query": self.last_query,
        }

    def check_budget(self, reserve: int = 0) -> None:
        if self.pf_calls + reserve >= self.max_pf_calls:
            raise RuntimeError("fixed per-case explicit PF budget exhausted")
        if time.monotonic() - self.started >= self.max_wall_seconds:
            raise RuntimeError("fixed per-case wall-clock budget exhausted")

    @property
    def pf_calls(self) -> int:
        return self.backend.pf_calls + self.replay_pf_calls + self.auxiliary_pf_calls

    def auxiliary_solve(self) -> None:
        self.check_budget(reserve=225)
        self.auxiliary_pf_calls += 1

    def auxiliary_failure(self) -> None:
        self.auxiliary_failed_pf_calls += 1

    def query(self, hour: int, action: list[int], energy: list[float]) -> dict:
        self.query_requests += 1
        self.last_query = {"hour": hour, "action": list(action), "energy_kwh": list(energy)}
        key = hour, tuple(action), tuple(energy)
        if key in self.cache:
            self.cache_hits += 1
            return self.cache[key]
        self.check_budget(reserve=225)
        backend = self.backend
        old_step, old_energy = backend.step, backend.energy
        try:
            backend.step, backend.energy = hour, list(energy)
            row = backend.preview(action)
            actual = []
            for name in backend.batteries:
                backend.circuit.SetActiveElement("Generator." + name)
                power = sum(float(v) for v in backend.circuit.ActiveCktElement.Powers[::2])
                if not math.isfinite(power):
                    raise ValueError("invalid battery terminal power")
                actual.append(-power)
            # This duplicates the pinned backend's ledger expression exactly;
            # every final result is independently replayed through advance().
            row["next_energy_kwh"] = [
                float(round(max(0.0, min(capacity, previous - power))))
                for previous, power, capacity in zip(energy, actual, backend.capacity, strict=True)
            ]
            row["battery_actual_kw"] = actual
            row["battery_command_kw"] = list(backend.commands_kw)
            clipped = [
                max(0.0, min(c, e - p))
                for e, p, c in zip(energy, actual, backend.capacity, strict=True)
            ]
            row["clipping_residual_kwh"] = [
                c - (e - p) for e, p, c in zip(energy, actual, clipped, strict=True)
            ]
            row["rounding_residual_kwh"] = [
                n - c for n, c in zip(row["next_energy_kwh"], clipped, strict=True)
            ]
            self.cache[key] = row
            return row
        finally:
            backend.step, backend.energy = old_step, old_energy

    def evaluate(self, schedule: list[list[int]]) -> dict:
        if len(schedule) != 24:
            raise ValueError("schedule must cover all 24 hours")
        energy, rows = list(self.backend.initial_energy), []
        previous, movements = self.initial_action, 0
        throughput = 0.0
        actual_net = [0.0] * len(energy)
        try:
            for hour, action in enumerate(schedule):
                row = self.query(hour, action, energy)
                rows.append(row)
                energy = row["next_energy_kwh"]
                throughput += math.fsum(abs(value) for value in row["battery_actual_kw"])
                actual_net = [
                    a + p for a, p in zip(actual_net, row["battery_actual_kw"], strict=True)
                ]
                movements += sum(
                    abs(a - b)
                    for a, b in zip(action[: self.devices], previous[: self.devices], strict=True)
                )
                previous = action
        except ValueError:
            return {"key": (math.inf, math.inf), "valid": False}
        valid = terminal_valid(
            self.backend.initial_energy,
            energy,
            len(rows),
            self.case["terminal_energy_tolerance_kwh"],
        ) and all(abs(value) <= 1.0 for value in actual_net)
        violation = math.fsum(row["voltage_violation_pu_hours"] for row in rows)
        loss = math.fsum(row["active_loss_kw"] for row in rows)
        return {
            "key": objective(violation, loss, movements) if valid else (math.inf, math.inf),
            "valid": valid,
            "voltage_violation_pu_hours": violation,
            "active_loss_kwh": loss,
            "movements": movements,
            "battery_throughput_kwh": throughput,
            "final_energy_kwh": energy,
            "actual_net_energy_kwh": actual_net,
        }

    def replay(self, schedule: list[list[int]], baseline: str) -> dict:
        """The original advance() exclusively determines final physical metrics."""
        self.check_budget()
        backend = QualificationBackend(self.case, self.assets)
        rows, error = [], None
        try:
            for action in schedule:
                self.check_budget(reserve=backend.pf_calls)
                before = list(backend.energy)
                row = backend.advance(action)
                clipped = [
                    max(0.0, min(c, e - p))
                    for e, p, c in zip(
                        before, row["battery_actual_kw"], backend.capacity, strict=True
                    )
                ]
                row["clipping_residual_kwh"] = [
                    c - (e - p)
                    for e, p, c in zip(before, row["battery_actual_kw"], clipped, strict=True)
                ]
                row["rounding_residual_kwh"] = [
                    n - c for n, c in zip(backend.energy, clipped, strict=True)
                ]
                rows.append(row)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        self.replay_pf_calls += backend.pf_calls
        self.replay_failed_pf_calls += backend.failed_pf_calls
        result = summarize(
            rows,
            initial_energy=backend.initial_energy,
            final_energy=backend.energy,
            cap_switches=backend.cap_switches,
            tap_moves=backend.tap_moves,
            step_hours=self.case["step_hours"],
            tolerance_kwh=self.case["terminal_energy_tolerance_kwh"],
            error=error,
        )
        result.update(
            baseline=baseline,
            trajectory=rows,
            battery_throughput_kwh=backend.throughput_kwh,
            replay_pf_calls=backend.pf_calls,
            failed_replay_pf_calls=backend.failed_pf_calls,
        )
        battery_count = len(backend.batteries)
        totals = {
            name: [math.fsum(row[field][i] for row in rows) for i in range(battery_count)]
            for name, field in (
                ("actual_net_energy_kwh", "battery_actual_kw"),
                ("commanded_net_energy_kwh", "battery_command_kw"),
                ("rounding_residual_kwh", "rounding_residual_kwh"),
                ("clipping_residual_kwh", "clipping_residual_kwh"),
            )
        }
        totals["actual_throughput_kwh"] = [
            math.fsum(abs(row["battery_actual_kw"][i]) for row in rows)
            for i in range(battery_count)
        ]
        totals["commanded_throughput_kwh"] = [
            math.fsum(abs(row["battery_command_kw"][i]) for row in rows)
            for i in range(battery_count)
        ]
        result.update(totals)
        result["qualification_valid"] = result["valid"] and all(
            abs(value) <= 1.0 for value in totals["actual_net_energy_kwh"]
        )
        result["nonzero_actual_throughput"] = backend.throughput_kwh > 1e-6
        estimate = self.evaluate(schedule)
        if (
            result["qualification_valid"] != estimate["valid"]
            or result["valid"]
            and (
                result["final_energy_kwh"] != estimate["final_energy_kwh"]
                or not math.isclose(
                    result["active_loss_kwh"],
                    estimate["active_loss_kwh"],
                    rel_tol=1e-9,
                    abs_tol=1e-7,
                )
                or not math.isclose(
                    result["voltage_violation_pu_hours"],
                    estimate["voltage_violation_pu_hours"],
                    abs_tol=1e-8,
                )
            )
        ):
            raise ValueError("query model and original-backend replay disagree")
        return result


def _device_options(evaluator: DayEvaluator, action: list[int], index: int) -> list[int]:
    return [0, 1] if index < evaluator.caps else list(range(33))


def current_idle(evaluator: DayEvaluator, parameters: dict) -> list[list[int]]:
    """Full current-model reference without future load access or battery use."""
    previous, schedule = list(evaluator.initial_action), []
    energy = list(evaluator.backend.initial_energy)
    for hour in range(24):
        memo = {}

        def key(action):
            identity = tuple(action)
            if identity not in memo:
                try:
                    row = evaluator.query(hour, action, energy)
                    move = sum(
                        abs(a - b)
                        for a, b in zip(
                            action[: evaluator.devices], previous[: evaluator.devices], strict=True
                        )
                    )
                    memo[identity] = objective(
                        row["voltage_violation_pu_hours"], row["active_loss_kw"], move
                    )
                except ValueError:
                    memo[identity] = (math.inf, math.inf)
            return memo[identity]

        starts = [list(previous)]
        for caps in itertools.product((0, 1), repeat=evaluator.caps):
            for tap in parameters["uniform_tap_starts"]:
                starts.append(
                    list(caps) + [tap] * (evaluator.devices - evaluator.caps) + [16] * len(energy)
                )
        starts = sorted(starts, key=key)[: parameters["retained_starts"]]
        finalists = []
        for chosen in starts:
            for _ in range(parameters["current_coordinate_passes"]):
                changed = False
                for index in range(evaluator.devices):
                    trials = [
                        chosen[:index] + [value] + chosen[index + 1 :]
                        for value in _device_options(evaluator, chosen, index)
                    ]
                    best = min([chosen, *trials], key=key)
                    changed |= best != chosen
                    chosen = best
                if not changed:
                    break
            finalists.append(chosen)
        previous = min(finalists, key=key)
        if not math.isfinite(key(previous)[0]):
            raise ValueError("current-model search found no converged candidate")
        schedule.append(list(previous))
    return schedule


def static_idle(evaluator: DayEvaluator, parameters: dict) -> list[list[int]]:
    """One constant device setting optimized against the complete load day."""
    energy = len(evaluator.backend.initial_energy)

    def key(action):
        return evaluator.evaluate([action] * 24)["key"]

    starts = [evaluator.initial_action]
    starts += [
        list(caps) + [tap] * (evaluator.devices - evaluator.caps) + [16] * energy
        for caps in itertools.product((0, 1), repeat=evaluator.caps)
        for tap in parameters["uniform_tap_starts"]
    ]
    finalists = []
    for chosen in sorted(starts, key=key)[: parameters["retained_starts"]]:
        for _ in range(parameters["static_coordinate_passes"]):
            changed = False
            for index in range(evaluator.devices):
                trials = [
                    chosen[:index] + [value] + chosen[index + 1 :]
                    for value in _device_options(evaluator, chosen, index)
                ]
                best = min([chosen, *trials], key=key)
                changed |= best != chosen
                chosen = best
            if not changed:
                break
        finalists.append(chosen)
    return [list(min(finalists, key=key)) for _ in range(24)]


def day_idle(
    evaluator: DayEvaluator, schedules: list[list[list[int]]], parameters: dict
) -> list[list[int]]:
    """Coordinate a full-day device sequence, including both adjacent transitions."""
    chosen = copy.deepcopy(min(schedules, key=lambda plan: evaluator.evaluate(plan)["key"]))
    for sweep in range(parameters["day_coordinate_passes"]):
        changed = False
        hours = range(24) if sweep % 2 == 0 else range(23, -1, -1)
        for hour in hours:
            for index in range(evaluator.devices):
                best, best_key = chosen, evaluator.evaluate(chosen)["key"]
                for value in _device_options(evaluator, chosen[hour], index):
                    if value == chosen[hour][index]:
                        continue
                    candidate = copy.deepcopy(chosen)
                    candidate[hour][index] = value
                    candidate_key = evaluator.evaluate(candidate)["key"]
                    if candidate_key < best_key:
                        best, best_key = candidate, candidate_key
                changed |= best != chosen
                chosen = best
        if not changed:
            break
    return chosen


def storage(
    evaluator: DayEvaluator, device_schedule: list[list[int]], parameters: dict
) -> tuple[list[list[int]], list[list[int]] | None]:
    """Greedy full-day paired dispatch; idle and best nonzero alternatives remain separate."""
    chosen, best_active, active_key = copy.deepcopy(device_schedule), None, (math.inf, math.inf)
    for _ in range(parameters["battery_coordinate_passes"]):
        changed = False
        for index in range(evaluator.devices, len(chosen[0])):
            winner, winner_key = chosen, evaluator.evaluate(chosen)["key"]
            for candidate in paired_schedules(
                chosen, index, parameters["battery_slots"], parameters["battery_amplitudes"]
            ):
                result = evaluator.evaluate(candidate)
                if (
                    result["valid"]
                    and result["battery_throughput_kwh"] > 1e-6
                    and (result["key"] < active_key)
                ):
                    best_active, active_key = candidate, result["key"]
                if result["key"] < winner_key:
                    winner, winner_key = candidate, result["key"]
            changed |= winner != chosen
            chosen = winner
        if not changed:
            break
    return chosen, best_active
