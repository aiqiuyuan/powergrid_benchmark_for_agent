ARG MAPDN_RUNTIME_IMAGE=mapdn-formal-runtime:1
FROM ${MAPDN_RUNTIME_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
COPY app/ /app/
WORKDIR /app
