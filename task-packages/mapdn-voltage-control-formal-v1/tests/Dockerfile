ARG MAPDN_RUNTIME_IMAGE=mapdn-formal-runtime:1
FROM ${MAPDN_RUNTIME_IMAGE}
COPY . /tests/
RUN mkdir -p /app/submission && chmod 700 /tests && chmod 755 /tests/test.sh
WORKDIR /tests
