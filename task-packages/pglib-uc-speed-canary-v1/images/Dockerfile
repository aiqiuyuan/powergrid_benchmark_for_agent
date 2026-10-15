FROM julia:1.10.11-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 bash tmux curl git ca-certificates procps gcc libseccomp-dev util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY Project.toml Manifest.toml /opt/uc-runtime/
ENV JULIA_PROJECT=/opt/uc-runtime JULIA_DEPOT_PATH=/opt/julia-depot \
    JULIA_NUM_THREADS=1 JULIA_NUM_GC_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 JULIA_PKG_PRECOMPILE_AUTO=0 PYTHONDONTWRITEBYTECODE=1
RUN julia --startup-file=no --project=/opt/uc-runtime -e \
    'using Pkg; Pkg.instantiate(); Pkg.precompile(); using HiGHS, JSON, JuMP'
COPY exec_candidate.c /tmp/exec_candidate.c
RUN gcc -Wall -Wextra -Werror /tmp/exec_candidate.c -lseccomp -o /usr/local/bin/uc-exec \
    && chmod -R a+rX /opt/julia-depot /opt/uc-runtime
WORKDIR /app
