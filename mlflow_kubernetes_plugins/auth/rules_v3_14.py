"""MLflow 3.14 authorization deltas layered on top of the earlier tables."""

from __future__ import annotations

from mlflow_kubernetes_plugins.auth._compat import (
    HAS_MCP_REGISTRY,
    AddItemsToReviewQueue,
    CreateLabelSchema,
    CreateReviewQueue,
    DeleteLabelSchema,
    DeleteReviewQueue,
    GetLabelSchema,
    GetLabelSchemaByName,
    GetOrCreateUserQueue,
    GetReviewQueue,
    GetReviewQueueByName,
    ListLabelSchemas,
    ListReviewQueueItems,
    ListReviewQueues,
    RemoveItemsFromReviewQueue,
    SetReviewQueueItemStatus,
    UpdateLabelSchema,
    UpdateReviewQueue,
)
from mlflow_kubernetes_plugins.auth.collection_filters import (
    COLLECTION_POLICY_RESPONSE_MCP_ACCESS_ENDPOINTS,
    COLLECTION_POLICY_RESPONSE_MCP_SERVERS,
)
from mlflow_kubernetes_plugins.auth.resource_names import (
    RESOURCE_NAME_PARSER_EXISTING_MCP_SERVER_NAME,
    RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,
    RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,
    RESOURCE_NAME_PARSER_MCP_SERVER_NAME,
)
from mlflow_kubernetes_plugins.auth.rules import (
    AuthorizationRule,
    _experiments_rule,
    _gateway_endpoints_use_rule,
    _mcp_servers_rule,
)


def apply_v3_14_deltas(
    *,
    request_authorization_rules: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]],
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    experiment_id_parsers = (RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,)

    request_authorization_rules.update(
        {
            # Label schema CRUD — experiment-scoped.
            # Endpoints carrying experiment_id get experiment-level resourceName checks.
            # ID-only endpoints (schema_id) fall back to workspace-level access.
            CreateLabelSchema: _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            GetLabelSchema: _experiments_rule("get"),
            GetLabelSchemaByName: _experiments_rule(
                "get", resource_name_parsers=experiment_id_parsers
            ),
            ListLabelSchemas: _experiments_rule("get", resource_name_parsers=experiment_id_parsers),
            UpdateLabelSchema: _experiments_rule("update"),
            DeleteLabelSchema: _experiments_rule("update"),
            # Review queue CRUD — experiment-scoped.
            CreateReviewQueue: _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            GetOrCreateUserQueue: _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            GetReviewQueue: _experiments_rule("get"),
            GetReviewQueueByName: _experiments_rule(
                "get", resource_name_parsers=experiment_id_parsers
            ),
            ListReviewQueues: _experiments_rule("get", resource_name_parsers=experiment_id_parsers),
            UpdateReviewQueue: _experiments_rule("update"),
            DeleteReviewQueue: _experiments_rule("update"),
            # Review queue item operations — queue_id only, workspace-level access.
            AddItemsToReviewQueue: _experiments_rule("update"),
            RemoveItemsFromReviewQueue: _experiments_rule("update"),
            ListReviewQueueItems: _experiments_rule("get"),
            SetReviewQueueItemStatus: _experiments_rule("update"),
        }
    )

    path_authorization_rules.update(
        {
            ("/ajax-api/3.0/mlflow/genai/evaluate/invoke", "POST"): _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            ("/gateway/openai/v1/responses/compact", "POST"): _gateway_endpoints_use_rule(
                resource_name_parsers=(RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,),
            ),
        }
    )

    if HAS_MCP_REGISTRY:
        apply_mcp_registry_deltas(path_authorization_rules=path_authorization_rules)


def apply_mcp_registry_deltas(
    *,
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    mcp_server_name_parsers = (RESOURCE_NAME_PARSER_MCP_SERVER_NAME,)
    existing_mcp_server_name_parsers = (RESOURCE_NAME_PARSER_EXISTING_MCP_SERVER_NAME,)

    for prefix in ("/ajax-api/3.0/mlflow/mcp-servers", "/api/3.0/mlflow/mcp-servers"):
        path_authorization_rules.update(
            {
                (prefix, "POST"): _mcp_servers_rule("create"),
                (prefix, "GET"): _mcp_servers_rule(
                    "list",
                    collection_policy=COLLECTION_POLICY_RESPONSE_MCP_SERVERS,
                ),
                (f"{prefix}/endpoints", "GET"): _mcp_servers_rule(
                    "list",
                    collection_policy=COLLECTION_POLICY_RESPONSE_MCP_ACCESS_ENDPOINTS,
                ),
                (f"{prefix}/<path:name>/versions", "POST"): _mcp_servers_rule(
                    "create",
                    resource_name_parsers=existing_mcp_server_name_parsers,
                    resource_name_verb="update",
                ),
                (f"{prefix}/<path:name>/versions", "GET"): _mcp_servers_rule(
                    "list",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/versions/<path:version>", "GET"): _mcp_servers_rule(
                    "get",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/versions/<path:version>", "PATCH"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/versions/<path:version>", "DELETE"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/versions/<path:version>/tags", "POST"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (
                    f"{prefix}/<path:name>/versions/<path:version>/tags/<path:key>",
                    "DELETE",
                ): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/endpoints", "POST"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/endpoints", "GET"): _mcp_servers_rule(
                    "list",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/endpoints/<endpoint_id>", "GET"): _mcp_servers_rule(
                    "get",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/endpoints/<endpoint_id>", "PATCH"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/endpoints/<endpoint_id>", "DELETE"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/tags", "POST"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/tags/<path:key>", "DELETE"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/aliases", "POST"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/aliases/<path:alias>", "GET"): _mcp_servers_rule(
                    "get",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/aliases/<path:alias>", "DELETE"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                # Keep the catch-all server routes last so nested MCP regexes win first.
                (f"{prefix}/<path:name>", "GET"): _mcp_servers_rule(
                    "get",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>", "PATCH"): _mcp_servers_rule(
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>", "DELETE"): _mcp_servers_rule(
                    "delete",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
            }
        )
