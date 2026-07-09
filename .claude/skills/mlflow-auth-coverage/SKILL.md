---
name: mlflow-auth-coverage
description: Adds auth coverage to the Kubernetes auth plugin for a new MLflow version. Use when the user asks to add auth support for a new MLflow release, update mlflow-integration for a new version, or create auth rules for new MLflow endpoints.
---

# MLflow Auth Coverage

Add authorization rule coverage to the `kubeflow/mlflow-integration` Kubernetes auth plugin for a new MLflow minor release.

Before writing code, read [reference.md](reference.md) for file patterns, auth mapping conventions, and review-established conventions.

## Prerequisites

1. The target MLflow version is released on PyPI.
2. The local `mlflow-integration` repo is checked out with a remote pointing to `kubeflow/mlflow-integration`.
3. The `pyproject.toml` upper bound currently excludes the target version.

## Workflow

1. **Create a branch** from the upstream `main`.
2. **Discover new endpoints** — install the target MLflow version and run the startup validator to find uncovered endpoints. Also check the MLflow changelog and release notes for new API surface.
3. **Inspect proto fields** — for each new proto request class, check which fields carry identifiers (`experiment_id`, `schema_id`, etc.) to determine the correct resource name parser. For path-based endpoints, read the handler source to find required parameters.
4. **Present a checkpoint** — summarize all discovered endpoints, proposed verb mappings, resource scoping decisions, and which endpoints get experiment-level vs workspace-level access.
5. **Implement** — modify files in the order listed in reference.md: `pyproject.toml`, `.github/workflows/tests.yml`, `mlflow_kubernetes_plugins/auth/_compat.py`, `mlflow_kubernetes_plugins/auth/rules_v3_XX.py` (new), `mlflow_kubernetes_plugins/auth/rules.py`, then `tests/test_auth.py`.
6. **Test across versions** — run the full test suite with the target version, the previous version, and the oldest supported version (currently 3.10). Confirm the startup validator passes on the target version.
7. **Lint and build** — `make python-lint` and `uv build`.
8. **End with a summary** — show the final diff, test results across all versions, and any open items. Do not push or create a PR. The user will request those explicitly when ready.

## Endpoint Discovery

Install the target version and use the startup validator to find gaps:

```bash
make install-dev
uv pip install "mlflow==<version>"
uv run --no-sync pytest -xvs -k "validate" tests/test_auth_fastapi.py
```

Any `MlflowException` listing uncovered endpoints tells you exactly what needs rules.

For proto-defined endpoints, find which proto module they live in and inspect fields:

```python
uv run --no-sync python3 -c "
import importlib
pb = importlib.import_module('mlflow.protos.<module>_pb2')
for name in ['CreateFoo', 'GetFoo', 'ListFoos']:
    cls = getattr(pb, name)
    fields = [f.name for f in cls.DESCRIPTOR.fields]
    print(f'{name}: {fields}')
"
```

For path-based (non-proto) endpoints, check handler source for required parameters:

```python
uv run --no-sync python3 -c "
import inspect
from mlflow.server.handlers import _some_handler
print(inspect.getsource(_some_handler))
"
```

Check whether any path-based endpoint carries `experiment_id` as a required parameter. If so, it needs `resource_name_parsers` for experiment-level RBAC.

## Auth Mapping Conventions

- All MLflow "list" operations map to K8s `get` verb, not `list`. The `get` verb is treated as blanket read access.
- All MLflow "create", "update", "delete", "add", "remove", "set" operations map to `update` verb.
- Experiment-scoped resources use `_experiments_rule(...)` with `RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME` when `experiment_id` is in the request.
- ID-only endpoints (`schema_id`, `queue_id`, etc.) with no tracking store lookup API use workspace-level access (no `resource_name_parsers`). Do not add raw database queries for ID resolution.
- New version-specific routes go ONLY in the delta file (`rules_v3_XX.py`), never in `rules_base.py`.
- Gateway proxy routes use `_gateway_endpoints_use_rule` with `RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME`.
- Gateway guardrails are workspace-scoped (not experiment sub-resources), so they use their own verbs (`create`, `delete`, `list`) rather than always mapping to `update`.

## Stop And Ask

Stop and ask the user when:
- A new endpoint introduces a resource type not in the current `ALLOWED_RESOURCES` set.
- The endpoint has a novel auth pattern not covered by existing `AuthorizationRule` fields.
- Proto imports fail or the endpoint registration pattern is unclear.
- The startup validator still fails after adding rules.
- The user asks to push, create a PR, or make any remote change — use the commit/PR title format `fix: add MLflow <version> auth coverage` and the official repo PR template from `.github/PULL_REQUEST_TEMPLATE.md`.

## Examples

User request examples that should trigger this skill:
- "Add auth coverage for MLflow 3.15."
- "Update mlflow-integration to support the new MLflow release."
- "Create auth rules for the new MLflow endpoints."
- "Add 3.16 support to the Kubernetes auth plugin."
