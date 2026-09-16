#!/usr/bin/env bash
set -euo pipefail

: "${KIND_CLUSTER_NAME:=mlflow-integration-$(date +%s)-${RANDOM}}"
: "${MLFLOW_TEST_IMAGE:=mlflow-integration:integration}"
: "${JUNIT_XML:=test-results/mlflow-integration.xml}"
: "${CONTAINER_TOOL:=docker}"

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
case "$CONTAINER_TOOL" in
  docker|podman) export KIND_EXPERIMENTAL_PROVIDER="$CONTAINER_TOOL" ;;
  *) echo "CONTAINER_TOOL must be docker or podman" >&2; exit 1 ;;
esac
# Podman qualifies short names with localhost; use the same name everywhere.
registry="${image_repository%%/*}"
if [[ "$CONTAINER_TOOL" == podman && ( "$image_repository" != */* || ( "$registry" != *.* && "$registry" != *:* && "$registry" != localhost ) ) ]]; then
  image_repository="localhost/${image_repository}"
fi
MLFLOW_TEST_IMAGE="${image_repository}:integration-$(date +%s)-${RANDOM}"

mkdir -p "$(dirname "$JUNIT_XML")"
created_cluster=false
cluster_ready=false
temporary_directory="$(mktemp -d)"
export KUBECONFIG="${temporary_directory}/kubeconfig"

cleanup() {
  status=$?
  if [[ "$cluster_ready" == true && "$status" != 0 ]]; then
    mkdir -p test-results/diagnostics
    kubectl get all --all-namespaces -o wide > test-results/diagnostics/resources.txt 2>&1 || true
    kubectl get events --all-namespaces --sort-by=.lastTimestamp > test-results/diagnostics/events.txt 2>&1 || true
    kubectl describe pods --all-namespaces > test-results/diagnostics/pods.txt 2>&1 || true
    kubectl logs deployment/mlflow --namespace mlflow > test-results/diagnostics/mlflow.log 2>&1 || true
  fi
  if [[ "$created_cluster" == true ]]; then
    kind delete cluster --name "$KIND_CLUSTER_NAME" || true
  fi
  rm -rf "$temporary_directory"
  exit "$status"
}
trap cleanup EXIT

clusters="$(kind get clusters)"
if grep -Fxq "$KIND_CLUSTER_NAME" <<< "$clusters"; then
  echo "Refusing to modify existing cluster ${KIND_CLUSTER_NAME}; choose a new KIND_CLUSTER_NAME" >&2
  exit 1
fi
# Mark ownership before creation so partial creation failures are cleaned up.
created_cluster=true
kind create cluster --name "$KIND_CLUSTER_NAME" --wait 2m
kubectl cluster-info --context "kind-$KIND_CLUSTER_NAME" >/dev/null
cluster_ready=true

"$CONTAINER_TOOL" build -f tests/kind/Dockerfile -t "$MLFLOW_TEST_IMAGE" .
if [[ "$CONTAINER_TOOL" == podman ]]; then
  podman save --format docker-archive --output "${temporary_directory}/image.tar" "$MLFLOW_TEST_IMAGE"
  kind load image-archive "${temporary_directory}/image.tar" --name "$KIND_CLUSTER_NAME"
else
  kind load docker-image "$MLFLOW_TEST_IMAGE" --name "$KIND_CLUSTER_NAME"
fi
helm upgrade --install mlflow charts/mlflow \
  --namespace mlflow --create-namespace --wait --timeout 5m \
  -f tests/kind/values-e2e.yaml \
  --set image.repository="${MLFLOW_TEST_IMAGE%:*}" \
  --set-string image.tag="${MLFLOW_TEST_IMAGE##*:}"

kubectl rollout status deployment/mlflow --namespace mlflow --timeout=180s
MLFLOW_INTEGRATION=1 MLFLOW_TEST_IMAGE="$MLFLOW_TEST_IMAGE" \
  uv run pytest tests/integration -m integration -v --junitxml="$JUNIT_XML"
