Read `/app/problem.md` and `/app/prompt.md`. Develop the general solver in
`/app/submission/solver.py`. All 45 original A/B/C instances, the pinned official
checker, and local development scoring are available under `/app/public` and
`/app/support`. Local ABC evaluation is unrestricted and does not use protected
feedback calls. Each protected call runs all 15 X cases at 900 seconds per case,
returning a complete structured JSON report, including per-case diagnostics.

Optimize the 900-second primary ranking: feasible case count first, then quality
Q with a fixed denominator of 15. Native reward is (feasible_count + Q) / 16.
Respect the configured protected-call budget and the 12-hour development limit.
The final submission is the workspace solver at cutoff, not an automatic rollback
to the best feedback candidate. A private 5400-second supplemental evaluation uses
the same frozen source after development, never feeds back, and never selects it.

Do not retrieve protected X inputs, reference solutions, historical answer tables,
or prior experiment artifacts. Do not inspect or modify the verifier or feedback
accounting. Submit one self-contained Python file using standard library, NumPy,
and SciPy. Read all detailed policies in the supplied task documents.
