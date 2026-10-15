# PowerGym canary problem contract

See [instruction.md](instruction.md) for the complete action, observation, failure,
terminal-energy and scalar-score contract. This is an executable native task
package for a workflow canary, not a certified benchmark release or paper reproduction.

Case selection is the first deterministically packed complete 34Bus profile,
index0, scale1, three source files explicitly ordered LoadShape1/2/3. It was fixed
before n=0/1 development. No comparison result is used to pick a case or weights.
`prepare.py` verifies every copied asset against `source-lock.json`, records all
source rows and truncation, and locks the 24-hour load matrix. Raw CSVs and full
checker stay only in the separate root-owned verifier. The development image has
only the controller, instructions and toy interface check. Public networking is
needed for the model gateway, with best-effort GitHub/HuggingFace domain blocks;
egress enforcement and residual source-reacquisition risk require deployment
acceptance, and the task does not claim a network-based strict-n proof.

Differences from upstream: explicit per-step snapshot load scaling; prior-snapshot
voltage observation after the first step; regulator winding2 and constant NumTaps32;
actual whole-circuit kWh scoring; hard ±1kWh terminal-energy rule. Generator battery
P/Q and integer-kWh update retain upstream semantics. This canary does not resolve
the physical power-factor model and does not assert that the original environment
was reproduced. Batteries have no extra efficiency model in this contract.

For every hourly power flow the runner checks `Solution.Converged`, finite positive
voltage and nonnegative finite actual loss, integrates the Generator terminal
active power, and retains a private trajectory during evaluation. Only declared
aggregate fields enter reward-details; no future arrays, full model objects,
trusted environment variables or simulator handles are passed to the controller.
