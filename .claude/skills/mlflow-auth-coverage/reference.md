# Reference

## File Change Order

Implement changes in this order. Each file has a specific pattern to follow.

### 1. `pyproject.toml`

Bump the MLflow upper bound to include the target version:

```toml
# For 3.XX coverage, set the ceiling to <3.(XX+1).0
"mlflow>=3.10.0,<3.15.0",
```

The tight upper bound is intentional for a security plugin — it prevents the plugin from silently accepting a new MLflow version with unprotected endpoints.

### 2. `.github/workflows/tests.yml`

Add the new version string to **both** CI matrices (`lint-and-test` and `test-static-prefix`):

```yaml
mlflow-version: ["3.10", "3.11", "3.12", "3.13", "<new-minor>"]
```

Keep versions quoted so YAML does not coerce `3.10` to `3.1`.

### 3. `mlflow_kubernetes_plugins/auth/_compat.py`

Add the version detection flag after the previous one:

```python
HAS_MLFLOW_3_XX_AUTH_SURFACE = MLFLOW_VERSION >= Version("3.XX.0.dev0")
```

Add conditional imports for new proto classes. If the proto module is new (not in `service_pb2`), use `importlib.import_module`:

```python
if HAS_MLFLOW_3_XX_AUTH_SURFACE:
    new_pb2 = importlib.import_module("mlflow.protos.new_pb2")
    CreateFoo = new_pb2.CreateFoo
    GetFoo = new_pb2.GetFoo
    # ...
else:  # pragma: no cover - exercised via MLflow version matrix
    CreateFoo = GetFoo = None
```

If the symbol exists in `service_pb2` across all supported versions (verify by installing the oldest supported version and checking), import it directly in the rules file instead of through `_compat.py`.

Update `__all__` alphabetically with all new exports including the new `HAS_MLFLOW_3_XX_AUTH_SURFACE` flag.

### 4. `mlflow_kubernetes_plugins/auth/rules_v3_XX.py` (NEW)

Create the delta file:

```python
"""MLflow 3.XX authorization deltas layered on top of the earlier tables."""

from __future__ import annotations

from mlflow_kubernetes_plugins.auth._compat import (
    CreateFoo,
    GetFoo,
    # ... all new proto classes from _compat
)
from mlflow_kubernetes_plugins.auth.resource_names import (
    RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,
    # ... any other parsers needed (e.g. RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME)
)
from mlflow_kubernetes_plugins.auth.rules import (
    AuthorizationRule,
    _experiments_rule,
    # ... any other rule helpers needed (e.g. _gateway_endpoints_use_rule)
)


def apply_v3_XX_deltas(
    *,
    request_authorization_rules: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]],
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    experiment_id_parsers = (RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,)

    request_authorization_rules.update(
        {
            # Endpoints with experiment_id get experiment-level resourceName checks.
            CreateFoo: _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            # ID-only endpoints fall back to workspace-level access.
            GetFoo: _experiments_rule("get"),
            # ...
        }
    )

    path_authorization_rules.update(
        {
            # Path-based endpoints that carry experiment_id should include parsers.
            ("/ajax-api/3.0/mlflow/some/route", "POST"): _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            # Gateway routes use the gateway endpoint use rule.
            ("/gateway/some/new/route", "POST"): _gateway_endpoints_use_rule(
                resource_name_parsers=(RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,),
            ),
        }
    )
```

### 5. `mlflow_kubernetes_plugins/auth/rules.py`

Add the import and conditional application block. Three changes:

**a) Import the flag** in the `_compat` import block:

```python
from mlflow_kubernetes_plugins.auth._compat import (
    # ... existing imports ...
    HAS_MLFLOW_3_XX_AUTH_SURFACE,
)
```

**b) Import the delta function** (after the previous version's import, with `# noqa: E402`):

```python
from mlflow_kubernetes_plugins.auth.rules_v3_XX import apply_v3_XX_deltas  # noqa: E402
```

**c) Add the conditional block** after the previous version's block:

```python
if HAS_MLFLOW_3_XX_AUTH_SURFACE:
    apply_v3_XX_deltas(
        request_authorization_rules=REQUEST_AUTHORIZATION_RULES,
        path_authorization_rules=PATH_AUTHORIZATION_RULES,
    )
```

### 6. `tests/test_auth.py`

Add three things:

**a) Imports** — add `HAS_MLFLOW_3_XX_AUTH_SURFACE` and all new proto classes to the `_compat` import block (alphabetically sorted).

**b) Rule coverage test** — place after the previous version's test and before `test_mlflow_prefixed_custom_path_authorization_rules_are_registered`:

```python
def test_mlflow_3XX_request_authorization_rules_cover_new_endpoints():
    if not HAS_MLFLOW_3_XX_AUTH_SURFACE:
        pytest.skip("Installed MLflow version does not expose the 3.XX request classes.")

    experiment_id_parsers = (RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,)

    rules = {
        CreateFoo: AuthorizationRule(
            "update", resource=RESOURCE_EXPERIMENTS,
            resource_name_parsers=experiment_id_parsers
        ),
        GetFoo: AuthorizationRule("get", resource=RESOURCE_EXPERIMENTS),
        # ... all proto-defined request rules
    }
    for request_class, expected_rule in rules.items():
        assert REQUEST_AUTHORIZATION_RULES[request_class] == expected_rule

    # Assert path-based rules
    some_path_rule = PATH_AUTHORIZATION_RULES[
        ("/ajax-api/3.0/mlflow/some/route", "POST")
    ]
    assert some_path_rule == AuthorizationRule(
        "update", resource=RESOURCE_EXPERIMENTS,
        resource_name_parsers=experiment_id_parsers
    )
```

**c) Gateway proxy test** — if the new version adds gateway proxy routes, append them to `test_gateway_proxy_post_routes_use_endpoint_name_parser`:

```python
if HAS_MLFLOW_3_XX_AUTH_SURFACE:
    routes.append(("/gateway/some/new/route", "POST"))
```

## Auth Mapping Reference

### Verb Mapping

| MLflow operation | K8s verb |
|---|---|
| create, update, delete, add, remove, set-status | `update` |
| get, get-by-name, list, search | `get` |

Exception: gateway guardrails use `create`, `delete`, `list` verbs because they are workspace-scoped resources, not experiment sub-resources.

### Resource Name Resolution

| Request field | Parser | Scope |
|---|---|---|
| `experiment_id` present | `RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME` | Experiment-level |
| ID-only (`schema_id`, `queue_id`, etc.) | None | Workspace-level |
| Gateway `endpoint_name` in path | `RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME` | Endpoint-level |
| `run_id` present | `RESOURCE_NAME_PARSER_RUN_ID_TO_EXPERIMENT_NAME` | Experiment-level (via lookup) |

When no tracking store API exists to resolve an ID to its parent experiment, use workspace-level access. Do not add raw database queries to work around missing store methods.

### Rule Helper Functions

| Helper | Resource constant |
|---|---|
| `_experiments_rule(verb, ...)` | `RESOURCE_EXPERIMENTS` |
| `_gateway_endpoints_rule(verb, ...)` | `RESOURCE_GATEWAY_ENDPOINTS` |
| `_gateway_endpoints_use_rule(...)` | `RESOURCE_GATEWAY_ENDPOINTS` with `subresource="use"` |
| `_gateway_guardrails_rule(verb, ...)` | `RESOURCE_GATEWAY_GUARDRAILS` |
| `_assistants_rule(verb, ...)` | `RESOURCE_ASSISTANTS` |
| `_registered_models_rule(verb, ...)` | `RESOURCE_REGISTERED_MODELS` |

## PR Conventions

### Commit / PR Title

```
fix: add MLflow <version> auth coverage
```

Conventional commits with `fix:` prefix.

### PR Description

Use the official repo template from `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
**What this PR does / why we need it**:

Adds MLflow <version> auth coverage to the Kubernetes auth plugin.

This updates the plugin to cover the new <version> auth surface, including:
- <feature area 1> endpoints (<scope>)
- <feature area 2> endpoints (<scope>)
- <new gateway route if any>

<Note about resource name resolution approach if relevant>

**Related Issues/PRs** _(use `Fixes #<number>` to auto-close, or `Relates to #<number>`)_:

**How is this PR tested?**

- [x] Existing unit tests
- [x] New unit tests
- [ ] Manual testing

**Does this PR require documentation update?**

- [x] No
- [ ] Yes (updated docs/ or README)

**Checklist:**

- [ ] Commits are signed off (DCO)
- [ ] Pre-commit hooks pass (`pre-commit run --all-files`)
- [x] Tests pass (`make python-test`)
```

## Established Conventions

These conventions are established in the codebase and enforced during review.

### Route placement

New version-specific routes go ONLY in the delta file (`rules_v3_XX.py`), never in `rules_base.py`. Routes in `rules_base.py` are the 3.10 baseline that applies to all versions.

### Test mocking completeness

When testing authorization for operations that touch gateway endpoints, the test must model ALL dependency permission checks (model-definitions, guardrails, etc.) that `_authorize_request` enforces, not just the primary resource.

### ID resolution without store APIs

When no upstream tracking store API exists to resolve a resource ID (e.g., `scorer_id`, `schema_id`, `queue_id`) to its parent experiment, use workspace-level access instead of adding raw database queries. This is an accepted trade-off.

### Cascade delete authorization

Deleting a parent resource that cascades to dependents (e.g., deleting a guardrail that removes endpoint guardrail configs) does not require authorizing each dependent resource. This is analogous to K8s owner-reference cleanup.

### Response filter type safety

When filtering response payloads, coerce numeric IDs to strings before authorization lookups. `_normalize_string()` only accepts `str` type and will silently drop numeric values.

### Naming convention consistency

When accessing response payload fields, check both `snake_case` and `camelCase` variants using `_first_present_value` for consistency with existing patterns.

### Fail-closed on misconfiguration

Do not silently correct user configuration errors. Let the system return an error so the misconfiguration is visible.

## Testing Checklist

- [ ] Run `make python-test` with the target MLflow version
- [ ] Run `make python-test` with the previous MLflow version (backward compat)
- [ ] Run `make python-test` with MLflow 3.10 (oldest supported)
- [ ] Run `make python-lint`
- [ ] Run `uv build`
- [ ] Startup validator passes (`test_create_app_validates_current_mlflow_startup_rules` in `tests/test_auth_fastapi.py`)
- [ ] New rule coverage test covers all proto rules + path rules
- [ ] Gateway proxy routes added to `test_gateway_proxy_post_routes_use_endpoint_name_parser` if applicable
- [ ] All path-based endpoints that carry `experiment_id` have `resource_name_parsers`
