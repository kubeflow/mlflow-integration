FROM python:3.12-slim

WORKDIR /src
COPY . .
RUN pip install --no-cache-dir "mlflow[extras,db,gateway,genai]" .

ENTRYPOINT ["mlflow"]
