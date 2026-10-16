Develop a Julia algorithm that solves the complete PGLib-UC problem and reaches
the fixed near-optimal reference quality as quickly as possible. Preserve the
original horizon, commitment, ramping, capacity, reserve and cost parameters.

Edit the source directory `/app/submission`, starting with `solver.jl` and
`pglib_model.jl`. The trusted grader executes your frozen source on an absolute
input path with an output directory, time limit and solver seed. Emit complete
`uc-schedule-v1` JSON snapshots through atomic rename. Full reference-quality
evaluation is available only through the framework when your feedback budget
permits it. Internal model computations on synthetic examples are allowed.

Create each temporary output file without truncation, for example
`open(path; write=true, create=true, truncate=false) do io ... end`, then rename
it within the same output directory. Use fresh unique filenames. Truncating
opens (including the usual `open(path, "w")`), file truncation, file metadata
changes and kernel keyrings are disabled by the sandbox on every kernel.

The algorithm receives one CPU, one solver thread, 8 GiB, no network and 300
seconds per replay, including startup, model building and output. Writes outside
the supplied output directory are forbidden. Do not use static solutions,
instance-specific lookup tables or state from another replay. Final source is
frozen at the development deadline; terminal scores do not return to development.

Quality is independently checked against a common valid full-problem lower
bound at 0.1% with a conservative numerical guard. Earlier valid target snapshots
score higher. Missing/invalid outputs, crashes and resource violations cannot
earn a reward. A normal deadline can retain an earlier valid incumbent.
