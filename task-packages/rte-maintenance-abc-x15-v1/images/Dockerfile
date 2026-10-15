FROM python:3.12-slim-bookworm
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libseccomp-dev util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/rte-requirements.txt
RUN pip install --no-cache-dir -r /opt/rte-requirements.txt
COPY exec_candidate.c /tmp/exec_candidate.c
RUN cc -O2 /tmp/exec_candidate.c -lseccomp -o /usr/local/bin/rte-exec \
    && rm /tmp/exec_candidate.c
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
