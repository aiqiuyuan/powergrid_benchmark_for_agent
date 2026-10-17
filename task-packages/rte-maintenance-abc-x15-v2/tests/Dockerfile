ARG RTE_RUNTIME_IMAGE=rte-abc-x15-runtime:1
FROM ${RTE_RUNTIME_IMAGE}
COPY . /tests/
RUN mkdir -p /app/submission && chmod 700 /tests && chmod 755 /tests/test.sh
WORKDIR /tests
