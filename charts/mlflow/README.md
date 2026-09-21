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
provide remote backend and artifact stores through a custom values file. When
`networkPolicy.enabled` is true, set `networkPolicy.ingressRules` to restrict
allowed source namespaces; an empty list preserves the standalone-compatible
allow-all ingress default. NetworkPolicy controls network reachability, not user
authorization. An Istio AuthorizationPolicy can restrict requests to a trusted
gateway principal. With `mlflow.authorizationMode=subject_access_review`, the
plugin then authorizes the gateway-provided user and groups through Kubernetes
SubjectAccessReviews. Direct-token deployments instead use
`self_subject_access_review`; do not treat caller-supplied identity headers as
authenticated identities on an unrestricted Service.

## Validation

The chart smoke test builds the production Dockerfile with the checked-out
plugin, loads a commit-tagged image into Kind, and installs the chart with
`image.pullPolicy=Never`. It checks Deployment readiness and the health endpoint
without depending on the published `latest` image. This validates the checkout,
not an existing release image or the complete Kubeflow gateway integration.

## Uninstalling

```bash
helm uninstall mlflow --namespace mlflow
```
