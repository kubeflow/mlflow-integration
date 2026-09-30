"""MLflow 3.16 authorization deltas layered on top of the earlier tables."""

from __future__ import annotations

from mlflow_kubernetes_plugins.auth.collection_filters import (
    COLLECTION_POLICY_RESPONSE_GATEWAY_MODELS,
)
from mlflow_kubernetes_plugins.auth.resource_names import (
    RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,
)
from mlflow_kubernetes_plugins.auth.rules import (
    AuthorizationRule,
    _assistants_rule,
    _gateway_endpoints_rule,
    _gateway_endpoints_use_rule,
)


def apply_v3_16_deltas(
    *,
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    path_authorization_rules.update(
        {
            (
                "/ajax-api/3.0/mlflow/assistant/sessions/<session_id>/tool-result",
                "POST",
            ): _assistants_rule("update"),
            ("/gateway/mlflow/v1/models", "GET"): _gateway_endpoints_rule(
                "get",
                collection_policy=COLLECTION_POLICY_RESPONSE_GATEWAY_MODELS,
            ),
            ("/gateway/typesafe/v1/systemone", "POST"): _gateway_endpoints_use_rule(
                resource_name_parsers=(RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,),
            ),
        }
    )
