# MLflow Helm Chart

This chart deploys MLflow with the Kubernetes workspace provider and optional
Kubernetes RBAC authorization plugin.

## Installation

### From GitHub Container Registry

Released charts are published to the Kubeflow Helm OCI registry. Set `VERSION`
to a repository release tag, including its leading `v`:

```bash
export VERSION=v1.6.0

helm upgrade --install mlflow oci://ghcr.io/kubeflow/charts/mlflow \
  --version "${VERSION#v}" \
  --namespace mlflow \
  --create-namespace \
  --set-string image.tag="$VERSION" \
  --set-string mlflow.backendStoreUri=sqlite:////mlflow/mlflow.db \
  --set-string mlflow.artifactsDestination=file:///mlflow/artifacts \
  --set storage.enabled=true
```

The chart version omits the leading `v`, while the matching image at
`ghcr.io/kubeflow/mlflow-integration` retains it. Replace the example version
with an available release from the repository's
[releases page](https://github.com/kubeflow/mlflow-integration/releases).
The inline SQLite and file artifact settings are intended for a standalone
deployment; configure remote stores before scaling the server.

### From a local checkout

From the repository root:

```bash
helm upgrade --install mlflow charts/mlflow \
  --namespace mlflow \
  --create-namespace \
  --values charts/mlflow/ci/values-standalone.yaml
```

## Configuration

See [`values.yaml`](values.yaml) for all configuration options and `ci/` for
standalone, multi-user, and optional-workload examples. For production,
provide remote backend and artifact stores through a custom values file.

## Uninstalling

```bash
helm uninstall mlflow --namespace mlflow
```
