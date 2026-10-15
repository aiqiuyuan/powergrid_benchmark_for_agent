ARG POWERGYM_RUNTIME_IMAGE=powergym-canary-runtime:1
FROM ${POWERGYM_RUNTIME_IMAGE}
COPY . /tests/
RUN chmod 700 /tests && chmod 755 /tests/test.sh && mkdir -p /app/submission
ENV POWERGYM_TESTS_DIR=/tests POWERGYM_STARTER=/tests/_reference/controller.py
WORKDIR /tests
