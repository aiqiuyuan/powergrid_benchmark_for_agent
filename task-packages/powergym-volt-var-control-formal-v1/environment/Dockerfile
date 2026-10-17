FROM python:3.12.14-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
COPY app/ /app/
WORKDIR /app
