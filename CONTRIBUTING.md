# Contributing to MLflow Kubeflow Integration

This guide explains how to contribute to the MLflow Kubeflow integration project.
For general Kubeflow contribution guidelines, please check the
[Kubeflow contributing guide](https://www.kubeflow.org/docs/about/contributing/).

## Requirements

- [Supported Python version](./pyproject.toml)
- [uv](https://docs.astral.sh/uv/)

## Development

Install development dependencies:

```bash
uv sync --extra dev
```

You can see all available Make targets by running:

```bash
make help
```

### Coding Style

Make sure to install [pre-commit](https://pre-commit.com/) and run `uv run pre-commit install` from
the root of the repository at least once before creating git commits.

The pre-commit hooks ensure code quality and consistency. They are executed in CI. PRs that fail
to comply with the hooks will not be able to pass the corresponding CI gate.

To check formatting:

```bash
make python-lint
```

To run all pre-commit hooks manually:

```bash
uv run pre-commit run --all-files
```

## Testing

Run the Python test suite:

```bash
make python-test
```

### CRD Verification

If you modify the MLflowConfig API types under `api/`, regenerate and verify the CRD artifacts.
This requires [Go](https://golang.org/) to be installed.

```bash
make generate-k8s
make verify-generated
```

### Helm Chart Verification

If you modify the chart under `charts/mlflow/`, lint every supported CI profile:

```bash
helm lint charts/mlflow -f charts/mlflow/ci/values-standalone.yaml
helm lint charts/mlflow -f charts/mlflow/ci/values-multi-user.yaml
helm lint charts/mlflow -f charts/mlflow/ci/values-workloads-enabled.yaml
helm package charts/mlflow --destination /tmp
```

### Building

To build the Python package:

```bash
uv build
```

### Publishing Releases

Pushing a `vX.Y.Z` tag publishes the Python package, container image, and Helm
chart through the repository's GitHub Actions workflows. The chart is published
to `oci://ghcr.io/kubeflow/charts/mlflow` at version `X.Y.Z`, while the matching
container image uses the `vX.Y.Z` tag. To recover a failed chart publication,
dispatch **Publish Helm Chart** with the existing release tag.

## Best Practices

### DCO Sign-Off

All commits must be signed off per the [Developer Certificate of Origin (DCO)](https://developercertificate.org/).
Use `git commit -s` to add the sign-off automatically.

### Kubeflow Enhancement Proposal (KEP)

For any significant features or enhancements, follow the
[Kubeflow Enhancement Proposal process](https://github.com/kubeflow/community/tree/master/proposals).
