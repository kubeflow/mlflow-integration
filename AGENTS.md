# AGENTS

## Project Layout

- Python package code lives in `mlflow_kubernetes_plugins/`.
- User-facing docs live in `README.md` and `docs/`.
- The MLflow Helm chart and its installation guide live in `charts/mlflow/`.
- Reusable Kubernetes manifests live in `examples/`.
- Architecture overview in `ARCHITECTURE.md`.

## Commands

```bash
# Setup
make install-dev                               # Sync development dependencies

# Lint
make python-lint                               # Lint entire project
uv run ruff check path/to/file.py              # Lint single file
uv run ruff check --fix path/to/file.py        # Lint and auto-fix single file
uv run ruff format path/to/file.py             # Format single file

# Type checking
make python-typecheck                          # Type-check entire project
uv run ty check path/to/file.py                # Type-check single file

# Testing
make python-test                               # Run the default test suite (excludes integration)
uv run pytest tests/test_auth.py               # Run single test file
uv run pytest tests/test_auth.py -k "pattern"  # Run tests matching pattern

# Build
uv build                                       # Build distribution artifacts

# Helm chart
helm lint charts/mlflow -f charts/mlflow/ci/values-standalone.yaml
helm lint charts/mlflow -f charts/mlflow/ci/values-multi-user.yaml
helm lint charts/mlflow -f charts/mlflow/ci/values-workloads-enabled.yaml
helm package charts/mlflow --destination /tmp  # Build a local chart archive

# Pre-commit
uv run pre-commit run --all-files              # Run all hooks

# Live integration
make kind-e2e                                    # Build the PR image and run the Kind smoke suite
```

## Key Conventions

- Preserve the MLflow entry point IDs `kubernetes` and `kubernetes-auth` unless you are intentionally making a breaking change.
- For auth coverage, preserve the explicit 1x1 mapping from MLflow endpoint to authorization requirement. Missing protected endpoint coverage should still fail at startup rather than falling back dynamically.
- In auth rule tables, readability and auditability are more important than deduplication. Keep duplicated literal route entries when that makes endpoint coverage clearer.
- GraphQL authorization must remain query-driven. Do not rely on `operationName` alone for authorization decisions.
- Release tags use the form `vX.Y.Z`. The Helm publishing workflow strips the leading `v` and publishes `oci://ghcr.io/kubeflow/charts/mlflow` at chart version `X.Y.Z`; the matching container image retains the `vX.Y.Z` tag.

## Patterns

- `rules_base.py` contains the consolidated authorization tables for the minimum supported MLflow version, currently 3.17.
- When adding auth rules for a newer MLflow version, create a new `rules_v3_XX.py` file (for example, `rules_v3_18.py`) with an `apply_v3_XX_deltas` function that updates the request and/or path rule tables. Register it in `rules.py`, guarded by the corresponding version flag in `_compat.py`, so the minimum supported version keeps its existing rules.
- When raising the minimum supported MLflow version, fold all deltas through that version into `rules_base.py` and remove the superseded delta files. Preserve effective permissions and route ordering, especially nested MCP routes before catch-all routes.
- When adding a new collection filter, follow the existing filters in `collection_filters.py`.
- When adding a new resource type for fine-grained RBAC, add the resource name extraction logic in `resource_names.py`.

## Before Finishing

- Use `make install-dev` to sync development dependencies locally.
- Before finishing, run `make python-lint`, `make python-typecheck`, `make python-test`, and
  `uv build` from the repository root when possible.
- For chart changes, also lint all profiles under `charts/mlflow/ci/` and package the chart.
