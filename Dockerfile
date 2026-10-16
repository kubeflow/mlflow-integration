FROM python:3.12-slim

COPY pyproject.toml README.md LICENSE /tmp/mlflow-kubernetes-plugins/
COPY mlflow_kubernetes_plugins/ /tmp/mlflow-kubernetes-plugins/mlflow_kubernetes_plugins/

RUN pip install --no-cache-dir "mlflow[extras,db,gateway,genai]" /tmp/mlflow-kubernetes-plugins \
    && rm -rf /tmp/mlflow-kubernetes-plugins

ENTRYPOINT ["mlflow"]
