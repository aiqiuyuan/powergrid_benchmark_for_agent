using Distributed
@everywhere begin
    using PowerModelsSecurityConstrained
    using PowerModels
    using JuMP
    using Ipopt
    using Memento
    const LOGGER = Memento.getlogger(PowerModelsSecurityConstrained)
end
using JSON
const PMSC = PowerModelsSecurityConstrained
pkgversion(PMSC) == v"0.12.0" || error("Unpinned PMSC version")
root = normpath(joinpath(dirname(pathof(PMSC)), ".."))
include(joinpath(root, "src", "scripts", "c1", "goc_c1_huristic.jl"))

app = get(ENV, "GOC_APP", "/app")
output = get(ENV, "GOC_OUTPUT", "/output")
config = JSON.parsefile(joinpath(@__DIR__, "baseline.json"))
native = joinpath(app, "native")
files = [joinpath(native, "case." * suffix) for suffix in ("con", "inl", "raw", "rop")]
stage = parse(Int, only(ARGS))
stage in (1, 2) || error("Unknown stage")
seconds = parse(Int, ENV["GOC_CODE$(stage)_SECONDS"])
mkpath(output)
if stage == 1
    # Upstream MyJulia1 reserves 60 seconds for startup; all time remains within
    # the independent host-enforced Code1 deadline.
    compute_c1_solution1(files..., max(1, seconds - 60), 2, "GOC1Backend";
        output_dir=output, scenario_id=config["scenario"], gurobi=false)
else
    if config["code2_mode"] == "strict-fp"
        # Explicit companion variant: unchanged upstream strict response solver.
        include(joinpath(root, "src", "scripts", "c1", "second-stage-fp.jl"))
    elseif config["code2_mode"] != "upstream-soft-fp"
        error("Unknown Code2 mode")
    end
    compute_c1_solution2(files..., max(1, seconds - 32), 2, "GOC1Backend";
        output_dir=output, scenario_id=config["scenario"])
end
isfile(joinpath(output, "solution$(stage).txt")) || error("No native output")
