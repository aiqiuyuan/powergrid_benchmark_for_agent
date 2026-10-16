FROM python:3.12.14-slim-bookworm AS sandbox-build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libseccomp-dev \
    && rm -rf /var/lib/apt/lists/*
COPY images/exec_candidate.c /tmp/exec_candidate.c
RUN gcc -O2 -Wall -Wextra /tmp/exec_candidate.c -lseccomp -o /tmp/exec-candidate

FROM python:3.12.14-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY images/requirements.txt /opt/powergym-requirements.txt
COPY images/requirements.lock /opt/powergym-requirements.lock
COPY images/wheels/ /opt/wheels/
RUN pip install --no-cache-dir --no-index --require-hashes --find-links=/opt/wheels \
    -r /opt/powergym-requirements.lock
COPY --from=sandbox-build /tmp/exec-candidate /usr/local/bin/exec-candidate
COPY images/controller_bridge.py /usr/local/lib/controller_bridge.py
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONHASHSEED=0
WORKDIR /app
