FROM python:3.12.14-slim-bookworm
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libseccomp-dev util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/mapdn-requirements.txt
COPY requirements.lock /opt/mapdn-requirements.lock
COPY wheels/ /opt/wheels/
RUN pip install --no-cache-dir --no-index --require-hashes --find-links=/opt/wheels \
    -r /opt/mapdn-requirements.lock
COPY exec_candidate.c /tmp/exec_candidate.c
RUN cc -O2 /tmp/exec_candidate.c -lseccomp -o /usr/local/bin/mapdn-exec \
    && rm /tmp/exec_candidate.c
COPY actor_worker.py /opt/mapdn/actor_worker.py
RUN chmod 755 /opt/mapdn && chmod 444 /opt/mapdn/actor_worker.py
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
