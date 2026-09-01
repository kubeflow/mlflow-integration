"""Explicit authorization rule tables for the Kubernetes auth plugin."""

from __future__ import annotations

from typing import NamedTuple

from mlflow_kubernetes_plugins.auth._compat import (
    HAS_MCP_REGISTRY,
    HAS_MLFLOW_3_11_AUTH_SURFACE,
    HAS_MLFLOW_3_12_AUTH_SURFACE,
    HAS_MLFLOW_3_13_AUTH_SURFACE,
    HAS_MLFLOW_3_14_AUTH_SURFACE,
    HAS_MLFLOW_3_15_AUTH_SURFACE,
)
from mlflow_kubernetes_plugins.auth.constants import (
    ALLOWED_RESOURCES,
    RESOURCE_ASSISTANTS,
    RESOURCE_DATASETS,
    RESOURCE_EXPERIMENTS,
    RESOURCE_GATEWAY_BUDGETS,
    RESOURCE_GATEWAY_ENDPOINTS,
    RESOURCE_GATEWAY_GUARDRAILS,
    RESOURCE_GATEWAY_MODEL_DEFINITIONS,
    RESOURCE_GATEWAY_SECRETS,
    RESOURCE_MCP_SERVERS,
    RESOURCE_REGISTERED_MODELS,
)
from mlflow_kubernetes_plugins.auth.graphql import _build_graphql_operation_rules


class AuthorizationRule(NamedTuple):
    verb: str | None
    resource: str | None = None
    subresource: str | None = None
    resource_name_parsers: tuple[str, ...] = ()
    collection_policy: str | None = None
    override_run_user: bool = False
    apply_workspace_filter: bool = False
    requires_workspace: bool = True
    deny: bool = False
    workspace_access_check: bool = False
    deny_message: str | None = None
    allow_if_resource_reference_missing: bool = False
    # Some hybrid endpoints act like a named-resource read when a reference is present, but
    # degrade to a broad collection read when it is absent. This flag allows response-filter
    # fallback only in the "reference missing" case, not when the named-resource check fails.
    fallback_to_collection_policy_on_missing_resource_reference: bool = False
    # Skip generic gateway dependency checks when a rule reuses a gateway resource for
    # authorization shape but does not actually consume that resource's usual dependencies.
    skip_gateway_dependency_permissions: bool = False


def _assistants_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_ASSISTANTS, **kwargs)


def _datasets_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_DATASETS, **kwargs)


def _experiments_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_EXPERIMENTS, **kwargs)


def _mcp_servers_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_MCP_SERVERS, **kwargs)


def _registered_models_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_REGISTERED_MODELS, **kwargs)


def _gateway_secrets_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_GATEWAY_SECRETS, **kwargs)


def _gateway_secrets_use_rule(**kwargs) -> AuthorizationRule:
    return _gateway_secrets_rule("create", subresource="use", **kwargs)


def _gateway_endpoints_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_GATEWAY_ENDPOINTS, **kwargs)


def _gateway_budgets_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_GATEWAY_BUDGETS, **kwargs)


def _gateway_guardrails_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_GATEWAY_GUARDRAILS, **kwargs)


def _gateway_endpoints_use_rule(**kwargs) -> AuthorizationRule:
    return _gateway_endpoints_rule("create", subresource="use", **kwargs)


def _gateway_model_definitions_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    return AuthorizationRule(verb, resource=RESOURCE_GATEWAY_MODEL_DEFINITIONS, **kwargs)


def _workspaces_rule(verb: str | None, **kwargs) -> AuthorizationRule:
    if verb is not None and not (
        kwargs.get("deny", False)
        or kwargs.get("apply_workspace_filter", False)
        or kwargs.get("workspace_access_check", False)
    ):
        raise ValueError(
            "_workspaces_rule requires deny=True, apply_workspace_filter=True, or "
            "workspace_access_check=True when verb is set."
        )
    if kwargs.get("deny", False) and kwargs.get("deny_message") is None:
        raise ValueError("_workspaces_rule requires deny_message when deny=True.")
    return AuthorizationRule(verb, resource=None, **kwargs)


def _normalize_resource_name(resource: str | None) -> str | None:
    if resource is None:
        return None
    normalized = resource.replace("_", "")
    if normalized not in ALLOWED_RESOURCES:
        raise ValueError(f"Unsupported RBAC resource '{resource}'")
    return normalized


from mlflow_kubernetes_plugins.auth.rules_base import (  # noqa: E402
    BASE_PATH_AUTHORIZATION_RULES,
    BASE_REQUEST_AUTHORIZATION_RULES,
)
from mlflow_kubernetes_plugins.auth.rules_v3_11 import apply_v3_11_deltas  # noqa: E402
from mlflow_kubernetes_plugins.auth.rules_v3_12 import apply_v3_12_deltas  # noqa: E402
from mlflow_kubernetes_plugins.auth.rules_v3_13 import apply_v3_13_deltas  # noqa: E402
from mlflow_kubernetes_plugins.auth.rules_v3_14 import apply_v3_14_deltas  # noqa: E402
from mlflow_kubernetes_plugins.auth.rules_v3_15 import (  # noqa: E402
    apply_mcp_registry_deltas,
    apply_v3_15_deltas,
)

REQUEST_AUTHORIZATION_RULES: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]] = dict(
    BASE_REQUEST_AUTHORIZATION_RULES
)
PATH_AUTHORIZATION_RULES: dict[
    tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
] = dict(BASE_PATH_AUTHORIZATION_RULES)

if HAS_MLFLOW_3_11_AUTH_SURFACE:
    apply_v3_11_deltas(
        request_authorization_rules=REQUEST_AUTHORIZATION_RULES,
        path_authorization_rules=PATH_AUTHORIZATION_RULES,
    )
if HAS_MLFLOW_3_12_AUTH_SURFACE:
    apply_v3_12_deltas(
        request_authorization_rules=REQUEST_AUTHORIZATION_RULES,
        path_authorization_rules=PATH_AUTHORIZATION_RULES,
    )
if HAS_MLFLOW_3_13_AUTH_SURFACE:
    apply_v3_13_deltas(
        request_authorization_rules=REQUEST_AUTHORIZATION_RULES,
        path_authorization_rules=PATH_AUTHORIZATION_RULES,
    )
if HAS_MCP_REGISTRY and not HAS_MLFLOW_3_15_AUTH_SURFACE:
    apply_mcp_registry_deltas(
        path_authorization_rules=PATH_AUTHORIZATION_RULES,
    )
if HAS_MLFLOW_3_14_AUTH_SURFACE:
    apply_v3_14_deltas(
        request_authorization_rules=REQUEST_AUTHORIZATION_RULES,
        path_authorization_rules=PATH_AUTHORIZATION_RULES,
    )
if HAS_MLFLOW_3_15_AUTH_SURFACE:
    apply_v3_15_deltas(
        request_authorization_rules=REQUEST_AUTHORIZATION_RULES,
        path_authorization_rules=PATH_AUTHORIZATION_RULES,
    )


GRAPHQL_OPERATION_RULES: dict[str, AuthorizationRule] = _build_graphql_operation_rules(
    AuthorizationRule, _normalize_resource_name
)


def _normalize_rules(
    value: AuthorizationRule | tuple[AuthorizationRule, ...],
) -> list[AuthorizationRule]:
    """Normalize a single rule or tuple of rules into a list."""
    if isinstance(value, AuthorizationRule):
        return [value]
    return list(value)


__all__ = [
    "AuthorizationRule",
    "GRAPHQL_OPERATION_RULES",
    "PATH_AUTHORIZATION_RULES",
    "REQUEST_AUTHORIZATION_RULES",
    "_normalize_rules",
]
