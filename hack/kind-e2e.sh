#!/usr/bin/env bash
set -euo pipefail

: "${KIND_CLUSTER_NAME:=mlflow-integration}"
: "${MLFLOW_TEST_IMAGE:=mlflow-integration:integration}"
: "${JUNIT_XML:=test-results/mlflow-integration.xml}"

image_name="${MLFLOW_TEST_IMAGE##*/}"
if [[ "$MLFLOW_TEST_IMAGE" == *@* || "$image_name" != *:* ]]; then
  echo "MLFLOW_TEST_IMAGE must be a tagged image reference" >&2
  exit 1
fi
image_repository="${MLFLOW_TEST_IMAGE%:*}"
if [[ -z "$image_repository" || -z "${MLFLOW_TEST_IMAGE##*:}" ]]; then
  echo "MLFLOW_TEST_IMAGE must be a tagged image reference" >&2
  exit 1
fi
MLFLOW_TEST_IMAGE="${image_repository}:integration-$(date +%s)-${RANDOM}"

mkdir -p "$(dirname "$JUNIT_XML")"
created_cluster=false

if ! kind get clusters | grep -Fxq "$KIND_CLUSTER_NAME"; then
  kind create cluster --name "$KIND_CLUSTER_NAME" --wait 2m
  created_cluster=true
fi
kubectl config use-context "kind-$KIND_CLUSTER_NAME"
kubectl cluster-info --context "kind-$KIND_CLUSTER_NAME" >/dev/null

cleanup() {
  status=$?
  if (( status != 0 )); then
    mkdir -p test-results/diagnostics
    kubectl get all --all-namespaces -o wide > test-results/diagnostics/resources.txt 2>&1 || true
    kubectl get events --all-namespaces --sort-by=.lastTimestamp > test-results/diagnostics/events.txt 2>&1 || true
    kubectl describe pods --all-namespaces > test-results/diagnostics/pods.txt 2>&1 || true
    kubectl logs deployment/mlflow --namespace mlflow > test-results/diagnostics/mlflow.log 2>&1 || true
  fi
  if [[ "$created_cluster" == true ]]; then
    kind delete cluster --name "$KIND_CLUSTER_NAME" || true
  fi
  exit "$status"
}
trap cleanup EXIT

"${CONTAINER_TOOL:-docker}" build -f tests/kind/Dockerfile -t "$MLFLOW_TEST_IMAGE" .
kind load docker-image "$MLFLOW_TEST_IMAGE" --name "$KIND_CLUSTER_NAME"
helm upgrade --install mlflow charts/mlflow \
  --namespace mlflow --create-namespace --wait --timeout 5m \
  -f tests/kind/values-e2e.yaml \
  --set image.repository="${MLFLOW_TEST_IMAGE%:*}" \
  --set-string image.tag="${MLFLOW_TEST_IMAGE##*:}"

kubectl rollout status deployment/mlflow --namespace mlflow --timeout=180s
MLFLOW_INTEGRATION=1 MLFLOW_TEST_IMAGE="$MLFLOW_TEST_IMAGE" \
  uv run pytest tests/integration -m integration -v --junitxml="$JUNIT_XML"
