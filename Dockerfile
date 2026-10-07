FROM python:3.12-slim AS builder

COPY pyproject.toml README.md LICENSE /build/plugin/
COPY mlflow_kubernetes_plugins /build/plugin/mlflow_kubernetes_plugins/
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels /build/plugin

FROM python:3.12-slim

# Update this pin together with the authorization rules and image startup check.
ARG MLFLOW_VERSION=3.15.2

# Only the packaged plugin crosses from the build stage into the runtime image.
COPY --from=builder /wheels/ /tmp/wheels/
RUN pip install --no-cache-dir "mlflow[extras,db,gateway,genai]==${MLFLOW_VERSION}" \
    /tmp/wheels/*.whl && rm -rf /tmp/wheels

ENTRYPOINT ["mlflow"]
