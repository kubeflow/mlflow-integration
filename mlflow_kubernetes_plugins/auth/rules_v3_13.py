"""MLflow 3.13 authorization deltas layered on top of the earlier tables."""

from __future__ import annotations

from mlflow.protos.service_pb2 import ListScorers

from mlflow_kubernetes_plugins.auth.collection_filters import (
    COLLECTION_POLICY_REQUEST_LIST_SCORERS,
)
from mlflow_kubernetes_plugins.auth.resource_names import (
    RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,
)
from mlflow_kubernetes_plugins.auth.rules import (
    AuthorizationRule,
    _assistants_rule,
    _experiments_rule,
    _gateway_endpoints_use_rule,
)


def apply_v3_13_deltas(
    *,
    request_authorization_rules: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]],
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    request_authorization_rules[ListScorers] = _experiments_rule(
        "list",
        collection_policy=COLLECTION_POLICY_REQUEST_LIST_SCORERS,
    )
    path_authorization_rules.update(
        {
            ("/ajax-api/3.0/mlflow/assistant/providers/<provider>/models", "GET"): _assistants_rule(
                "get"
            ),
            ("/gateway/proxy/<endpoint_name>/<path:path>", "POST"): _gateway_endpoints_use_rule(
                resource_name_parsers=(RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,)
            ),
        }
    )
