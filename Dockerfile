FROM python:3.12-slim

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY mlflow_kubernetes_plugins ./mlflow_kubernetes_plugins
RUN pip install --no-cache-dir "mlflow[extras,db,gateway,genai]" .

ENTRYPOINT ["mlflow"]
