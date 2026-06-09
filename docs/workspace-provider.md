# Workspace Provider

The `kubernetes` workspace provider exposes Kubernetes namespaces as MLflow workspaces. Each MLflow workspace maps 1:1 to a namespace, so workspace lifecycle stays external to MLflow.

If you need the upstream MLflow workspace concepts first, read the official guide: <https://mlflow.org/docs/latest/self-hosting/workspaces/getting-started/>.

## What It Does

- lists Kubernetes namespaces as workspaces
- watches namespaces in the background so listings stay warm
- filters built-in system namespaces such as `kube-*` and `openshift-*`
- optionally filters namespaces with a label selector
- reads workspace descriptions from the `mlflow.kubeflow.org/workspace-description` annotation
- supports per-namespace artifact root overrides through the optional `MLflowConfig` CRD
- supports per-namespace trace archival location and retention overrides through the optional `MLflowConfig` CRD when the server runs MLflow `3.13+`
- exposes resolved artifact root overrides through workspace metadata when available
- exposes resolved trace archival override metadata when the installed MLflow version supports it
- keeps workspace CRUD read-only because namespace management belongs to Kubernetes

## Installation

```bash
pip install mlflow-kubernetes-plugins
```

## Configuration

The provider reads configuration from environment variables, constructor arguments, and `kubernetes://` URI query parameters. URI parameters win over environment variables.

### Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MLFLOW_K8S_WORKSPACE_LABEL_SELECTOR` | unset | Limits visible namespaces to those matching a Kubernetes label selector. |
| `MLFLOW_K8S_DEFAULT_WORKSPACE` | unset | Workspace to use when a request omits explicit workspace context. |
| `MLFLOW_K8S_NAMESPACE_EXCLUDE_GLOBS` | built-in exclusions | Extra comma-separated glob patterns to hide. |

### Workspace URI Parameters

Pass the same values through the workspace store URI when you want per-deployment overrides:

- `label_selector`
- `default_workspace`
- `namespace_exclude_globs`

Example:

```bash
mlflow server \
  --backend-store-uri postgresql://user:pass@localhost/mlflow \
  --default-artifact-root s3://mlflow-artifacts \
  --enable-workspaces \
  --workspace-store-uri "kubernetes://?label_selector=mlflow-enabled%3Dtrue&default_workspace=team-a"
```

## Running The Server

The provider loads in-cluster Kubernetes credentials first and falls back to the local kubeconfig. That allows the same plugin to work in a cluster or from a development workstation.

```bash
export MLFLOW_K8S_WORKSPACE_LABEL_SELECTOR="mlflow-enabled=true"
export MLFLOW_K8S_DEFAULT_WORKSPACE="team-a"

mlflow server \
  --backend-store-uri postgresql://user:pass@localhost/mlflow \
  --default-artifact-root s3://mlflow-artifacts \
  --enable-workspaces \
  --workspace-store-uri "kubernetes://"
```

## Client Usage

Clients still use standard MLflow workspace APIs and headers:

- call `mlflow.set_workspace("team-a")`
- set `MLFLOW_WORKSPACE=team-a`
- or send `X-MLFLOW-WORKSPACE: team-a`

If `MLFLOW_K8S_DEFAULT_WORKSPACE` is unset and the client does not specify a workspace, the server returns an "Active workspace is required" error.

## Artifact Root Overrides

If the optional `MLflowConfig` CRD is installed, a namespace can override the server's default artifact root for the MLflow workspace. The CRD uses fixed identifiers:

- `metadata.name` must be `mlflow`
- when set, `spec.artifactRootSecret` must be `mlflow-artifact-connection`
- `spec.artifactRootPath` is the user-configurable path suffix under that secret's bucket

The plugin reads:

- `spec.artifactRootSecret` for the secret containing `AWS_S3_BUCKET`
- `spec.artifactRootPath` for an optional path suffix under that bucket

Important behavior:

- the provider currently reads only `AWS_S3_BUCKET` from `artifactRootSecret` to derive the workspace artifact root
- workspace-scoped credential retrieval and injection are not supported yet; artifact operations still use the MLflow server's existing backend credential chain

Install the generated CRD from `config/crd/bases/mlflow.kubeflow.org_mlflowconfigs.yaml` before creating namespace-specific overrides.

This lets each namespace point to a different object store location without changing MLflow server startup flags.

When the override resolves cleanly, `get_workspace` and `list_workspaces` expose it through the workspace `default_artifact_root` field.

Artifact overrides are independent from trace archival overrides: a namespace can configure one, both, or neither.

## Trace Archival Overrides

On MLflow `3.13+`, the same `MLflowConfig` CRD can also override the workspace trace archival root and broader retention used by the server-owned archival scheduler.

The trace archival fields use a separate fixed secret contract:

- when set, `spec.archiveRootSecret` must be `mlflow-archive-secret`
- `spec.archiveRootPath` is the user-configurable path suffix under that secret's bucket
- `spec.traceArchivalRetention` uses MLflow's duration format such as `30d`, `12h`, or `90m`

The provider reads:

- `spec.archiveRootSecret` for the secret containing `AWS_S3_BUCKET`
- `spec.archiveRootPath` for an optional path suffix under that bucket
- `spec.traceArchivalRetention` for the workspace-level broader retention override

Important behavior:

- these fields only take effect when the MLflow server is running version `3.13+`
- `traceArchivalRetention` can be configured independently of `archiveRootSecret` / `archiveRootPath`
- when `archiveRootSecret` and optional `archiveRootPath` are set, the resolved location becomes the effective workspace trace archival root, matching upstream MLflow `3.13+` workspace behavior
- the provider currently reads only `AWS_S3_BUCKET` from `archiveRootSecret` to derive the workspace archive root
- workspace-scoped credential retrieval and injection are not supported yet; archive writes still use the MLflow server's existing backend credential chain today

Example:

```yaml
apiVersion: mlflow.kubeflow.org/v1
kind: MLflowConfig
metadata:
  name: mlflow
  namespace: team-a
spec:
  archiveRootSecret: mlflow-archive-secret
  archiveRootPath: traces
  traceArchivalRetention: 14d
```

With that configuration, the provider resolves the effective workspace archive root as `s3://<bucket-from-mlflow-archive-secret>/traces` and MLflow archives directly under that workspace root.
