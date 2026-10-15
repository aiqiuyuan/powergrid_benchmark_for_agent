Read `/app/problem.md` and `/app/prompt.md`. Develop the general solver in
`/app/submission/solver.py`. All 45 original A/B/C instances, the pinned official
checker, and local development scoring are available under `/app/public` and
`/app/support`. Local ABC evaluation is unrestricted and does not use protected
feedback calls. The protected evaluator always runs the complete 15-case X panel
at 900 seconds per case in parallel, returning only aggregate feedback.

Respect the experiment's configured protected-call budget and 12-hour development
limit. Do not retrieve protected X inputs, reference solutions, historical answer
tables, or prior experiment artifacts. Do not inspect or modify the verifier or
feedback accounting. Final submission is one self-contained Python file using
the installed standard library, NumPy, and SciPy. A separate, private frozen-source
5400-second evaluation is performed after development ends and is never returned
to the development agent.
