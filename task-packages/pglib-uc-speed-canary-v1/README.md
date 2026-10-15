# UC speed canary preparation

Status: source-executing preparation package; **not a certified or submitted task**.
See [the task card](../../docs/task-cards/unit-commitment.md#14-n01流程小测准备2026-10-15)
and [the paired preparation profile](../../configs/unit-commitment-speed.canary.json).

This package replaces static schedule grading with execution of a frozen Julia
source directory. The trusted supervisor copies complete snapshots, timestamps
their receipt, and validates them in separate checker subprocesses. Candidate
costs, bounds, timestamps and status labels are never authoritative. The original
PGLib MILP starter and independent schedule checker derive from the historical
adapter; the PGLib MIT license is included.

The paired canary has one n=0 and one n=1 development run on one complete original
RTS case. The case is used to check the workflow; selection of the main case and
the three strong-baseline calibration remain open. The inherited 12-hour limit
remains until a shorter canary duration is explicitly selected. No aggregate
token cap, token reservation or output-token override is configured.

## Candidate contract

The submission is a flat directory containing `solver.jl` plus Julia source and
documentation, at most 32 files and 2 MiB. The trusted caller supplies:

```text
julia --startup-file=no --threads=1 solver.jl ABSOLUTE_INSTANCE OUTPUT_DIRECTORY SECONDS SEED
```

Write at most 64 complete `*.json` snapshots, each at most 16 MiB, using a
temporary file then atomic rename. Use unique final filenames. The output schema
is `uc-schedule-v1`: thermal `on`, `power`, `reserve`, and renewable generation
arrays for the full horizon. The known mathematical model/schema is available to
the developer; the complete target input, reference and checker are available
only to the trusted grader. Static answers or instance lookup tables are forbidden;
source review and input-variation probes remain required acceptance gates.

Candidate execution has one CPU and an 8 GiB container memory cap. The launcher
drops privileges, pins CPU affinity and restricts process creation, network and
cross-replay writes. Landlock ABI >=3 is required; unsupported kernels fail closed.
Julia runtime threads are allowed but share the one CPU. The supervisor freezes
source once before all replays. Neither developer root nor candidate UID can
write the trusted grader's private directories.

## Staging and launch gates

1. Build `images/Dockerfile` with its pinned Julia dependency manifest. Record the
   immutable runtime image identity and use it in both task Dockerfiles. The
   current image tag is a preparation placeholder, not a frozen release digest.
2. Copy `support/` into the staged task's `tests/support/`. Copy the externally
   prepared private `instance.json` and reference `manifest.json` into
   `tests/data/`; never copy them into `environment/app/`.
3. The private manifest requires `instance`, `instance_sha256`,
   `execution_seconds`, `reference_upper`, `reference_lower`, `target_gap_ratio`
   and `deployment_accepted`. Keep the latter false until the tested code,
   input/reference, image, access policy and resource receipts have been frozen.
4. Run local scoring tests and the real Linux launcher probe. Then run real Julia
   and HiGHS under the target container's restrictions, including timeout,
   invalid output, crash, memory exhaustion and cross-replay cache probes.
5. Bind a **time-only host model bridge** and the native counted judge bridge to
   the otherwise offline developer. The historical token-capped gateway cannot
   be reused unchanged. For n=0 there must be no judge service or submit route.
   For n=1 set trusted judge `UC_SPEED_PHASE=feedback`, one CPU, 8 GiB, and a
   480-second total feedback timeout. Terminal verifier uses the default
   `UC_SPEED_PHASE=terminal`, three seeds and a 1320-second timeout. These
   environment values are trusted deployment settings, not candidate inputs.
6. Verify accepted-call counting, transport retry/idempotency, over-budget
   rejection, result collection, cutoff freezing, late-result handling, no
   score bypass and a real model API/tool call without an aggregate token cap.
   Native framework counters alone do not establish all of these properties.
7. Submit exactly two canary jobs using the new CFS and CLI after migration and
   login acceptance. Save intent and job receipts; recover unknown submissions
   by exact identity before retrying. The main experiment starts only after
   reviewing the paired canary and passing its separate scientific gates.

No launch command is supplied while these gates are incomplete. Editing
`deployment_accepted` alone is not acceptance evidence.

## Verification

```bash
python -m unittest discover -s task-packages/pglib-uc-speed-canary-v1/verification -v
```

Linux root with `uc-exec` installed can additionally run
`verification/probe_linux_sandbox.py`. This checks real privileges, threads,
private reads, forbidden `/tmp`/`/dev/shm` writes, and output writes. It does not
certify Julia, container memory accounting, the model gateway or native Harbor.
The ABI compatibility constant follows the Linux UAPI
[v6.1 headers](https://raw.githubusercontent.com/torvalds/linux/v6.1/include/uapi/linux/landlock.h)
and requires runtime ABI 3; old headers must not silently weaken the restriction.

The 2026-10-15 trusted local full-case run reached reference quality in about
52.05 seconds, with about 0.03 seconds of independent checking. It used macOS
without the Linux sandbox and is a functional check, not a cluster speed result
or main-study calibration. Raw evidence is stored in the user's local canary plan.
