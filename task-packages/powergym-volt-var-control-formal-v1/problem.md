# PowerGym formal v1 contract

The case is the already qualified `123Bus-stress-p000-s2.5`: profile zero, 2.5×
load multipliers, all24 hourly rows. Its bytes and assets are pinned in
[source-lock.json](source-lock.json), copied from the immutable selection pool.
The case was chosen after traditional device/storage qualification and before
this formal n experiment. The development feedback case and final case are the
same complete fixed day. Calendar independence is unverified.

[The participant instructions](instruction.md) define the complete contract.
Voltage is a soft cost. Validity requires legal actions, converged finite full
trajectories, every battery's integer ledger within1kWh of its initial energy,
and its actual terminal active-power net integral within1kWh. The latter closes
the integer-rounding energy loophole; it is an explicit formal contract addition.
The original canary and historical outputs remain unchanged.

The standalone backend derives from the reviewed selection implementation with
the qualification numerical wrapper copied into this package. Cold initialization
and1e-10 tolerance apply to initialization and each hourly solve. Native Generator
P/Q, projection, clip, Python round, initial devices and observation timing are
unchanged. Battery throughput and clip/round residuals are separately reported.
No added efficiency model is assumed. The benchmark quality scales1000kWh/33 tap
steps are benchmark design choices, not paper scoring or paper reproduction.

The trusted reference parity script reads historical qualified action plans in a
private temporary directory and compares every physical row through this exact
runner. It exports only hashes and summaries. Plan replay certifies numerical
parity, not a legal participant controller. `hold_idle`, `canary_hysteresis`, and
`coordinated_voltage` were defined using the same lagged observations. The model
snapshot/strong_current references have current-load and full-model privileges;
static/day and storage oracle references can see the whole day. These privileged
references are separate contextual comparisons, not same-information baselines
or certified global optima. The initial submitted controller for every n condition is the previously
measured `coordinated_voltage` policy, the strongest of the existing legal
observation-only references on this case. The historical hysteresis policy
remains a separate reference and the old canary is unchanged.

The development image contains only the controller and synthetic interface check.
The separate verifier keeps full data, hashes and trajectories root-owned. Only
allowlisted daily aggregates enter feedback. Trusted numerical acceptance on
macOS is not Linux sandbox acceptance. The deployment must separately run the
copied UID/seccomp/Landlock probes, file/IPC/network isolation tests, offline
wheel/image verification, and platform feedback-count/final-collection checks.
