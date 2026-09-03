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
cluster_ready=false
previous_context="$(kubectl config current-context 2>/dev/null || true)"
test_namespace="${MLFLOW_TEST_NAMESPACE:-mlflow-tests}"
workspace_a="${MLFLOW_TEST_WORKSPACE_A:-mlflow-workspace-a}"
workspace_b="${MLFLOW_TEST_WORKSPACE_B:-mlflow-workspace-b}"
hidden_workspace="${MLFLOW_TEST_HIDDEN_WORKSPACE:-mlflow-workspace-hidden}"

clean_reused_cluster() {
  helm uninstall mlflow --namespace mlflow --wait --timeout 5m || true
  kubectl delete namespace mlflow "$test_namespace" "$workspace_a" "$workspace_b" \
    "$hidden_workspace" --ignore-not-found --wait=true || true
  kubectl delete clusterrole mlflow-workspace-discovery --ignore-not-found || true
  kubectl delete clusterrolebinding workspace-a-discovery --ignore-not-found || true
}

cleanup() {
  status=$?
  if [[ "$cluster_ready" == true && "$status" != 0 ]]; then
    mkdir -p test-results/diagnostics
    kubectl get all --all-namespaces -o wide > test-results/diagnostics/resources.txt 2>&1 || true
    kubectl get events --all-namespaces --sort-by=.lastTimestamp > test-results/diagnostics/events.txt 2>&1 || true
    kubectl describe pods --all-namespaces > test-results/diagnostics/pods.txt 2>&1 || true
    kubectl logs deployment/mlflow --namespace mlflow > test-results/diagnostics/mlflow.log 2>&1 || true
  fi
  if [[ "$cluster_ready" == true && "$created_cluster" != true ]]; then
    clean_reused_cluster
  fi
  if [[ "$created_cluster" == true ]]; then
    kind delete cluster --name "$KIND_CLUSTER_NAME" || true
  fi
  if [[ -n "$previous_context" ]]; then
    kubectl config use-context "$previous_context" >/dev/null 2>&1 || true
  else
    kubectl config unset current-context >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT

if ! kind get clusters | grep -Fxq "$KIND_CLUSTER_NAME"; then
  kind create cluster --name "$KIND_CLUSTER_NAME" --wait 2m
  created_cluster=true
fi
kubectl config use-context "kind-$KIND_CLUSTER_NAME"
kubectl cluster-info --context "kind-$KIND_CLUSTER_NAME" >/dev/null
cluster_ready=true
if [[ "$created_cluster" != true ]]; then
  clean_reused_cluster
fi

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
