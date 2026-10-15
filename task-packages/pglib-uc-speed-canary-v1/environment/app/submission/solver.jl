# Full original PGLib-UC MILP starter. Candidate-reported bounds are not scored.
using JSON, JuMP, HiGHS
include(joinpath(@__DIR__, "pglib_model.jl"))

function main()
    length(ARGS) == 4 || error("solver.jl INSTANCE OUTPUT_DIRECTORY SECONDS SEED")
    instance, output, limit, seed = ARGS
    isabspath(instance) || error("Absolute instance path required")
    data = JSON.parsefile(instance)
    model = build_pglib(data)
    set_optimizer(model, HiGHS.Optimizer)
    set_optimizer_attribute(model, "threads", 1)
    set_optimizer_attribute(model, "random_seed", parse(Int, seed))
    set_optimizer_attribute(model, "mip_rel_gap", 1e-4)
    set_optimizer_attribute(model, "mip_feasibility_tolerance", 1e-7)
    set_time_limit_sec(model, max(0.1, parse(Float64, limit) - 15))
    optimize!(model)
    has_values(model) || return
    thermal = Dict()
    for (g, gen) in data["thermal_generators"]
        on = [round(Int, value(model[:ug][g, t])) for t in 1:data["time_periods"]]
        thermal[g] = Dict("on" => on,
            "power" => [value(model[:pg][g, t]) + gen["power_output_minimum"] * on[t]
                        for t in 1:data["time_periods"]],
            "reserve" => [value(model[:rg][g, t]) for t in 1:data["time_periods"]])
    end
    renewable = Dict(g => [value(model[:pw][g, t]) for t in 1:data["time_periods"]]
                     for g in keys(data["renewable_generators"]))
    schedule = Dict("schema" => "uc-schedule-v1", "thermal" => thermal,
                    "renewable" => renewable)
    mkpath(output)
    path = joinpath(output, "0001.json")
    open(path * ".tmp", "w") do file
        JSON.print(file, schedule)
    end
    mv(path * ".tmp", path)
end

main()
