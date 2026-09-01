"""MLflow 3.15 authorization deltas layered on top of the earlier tables."""

from __future__ import annotations

from mlflow_kubernetes_plugins.auth._compat import CreatePresignedDownloadUrl
from mlflow_kubernetes_plugins.auth.collection_filters import (
    COLLECTION_POLICY_RESPONSE_MCP_ACCESS_ENDPOINTS,
    COLLECTION_POLICY_RESPONSE_MCP_SERVERS,
)
from mlflow_kubernetes_plugins.auth.resource_names import (
    RESOURCE_NAME_PARSER_ARTIFACT_EXPERIMENT_ID_TO_NAME,
    RESOURCE_NAME_PARSER_MCP_SERVER_NAME,
    RESOURCE_NAME_PARSER_RUN_ID_TO_EXPERIMENT_NAME,
)
from mlflow_kubernetes_plugins.auth.rules import (
    AuthorizationRule,
    _assistants_rule,
    _experiments_rule,
    _mcp_servers_rule,
)


def apply_v3_15_deltas(
    *,
    request_authorization_rules: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]],
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    if CreatePresignedDownloadUrl is not None:
        request_authorization_rules[CreatePresignedDownloadUrl] = _experiments_rule(
            "get",
            resource_name_parsers=(RESOURCE_NAME_PARSER_RUN_ID_TO_EXPERIMENT_NAME,),
        )

    artifact_path_parsers = (RESOURCE_NAME_PARSER_ARTIFACT_EXPERIMENT_ID_TO_NAME,)
    path_authorization_rules.update(
        {
            (
                "/ajax-api/3.0/mlflow/assistant/sessions/<session_id>/permission",
                "POST",
            ): _assistants_rule("update"),
            ("/ajax-api/3.0/mlflow/assistant/providers", "GET"): _assistants_rule("get"),
            ("/api/2.0/mlflow-artifacts/artifacts/<path:artifact_path>", "GET"): _experiments_rule(
                "get",
                resource_name_parsers=artifact_path_parsers,
            ),
            ("/ajax-api/2.0/mlflow-artifacts/artifacts/<path:artifact_path>", "GET"): (
                _experiments_rule(
                    "get",
                    resource_name_parsers=artifact_path_parsers,
                )
            ),
            ("/api/2.0/mlflow-artifacts/artifacts/<path:artifact_path>", "PUT"): _experiments_rule(
                "update",
                resource_name_parsers=artifact_path_parsers,
            ),
            ("/ajax-api/2.0/mlflow-artifacts/artifacts/<path:artifact_path>", "PUT"): (
                _experiments_rule(
                    "update",
                    resource_name_parsers=artifact_path_parsers,
                )
            ),
        }
    )

    apply_mcp_registry_deltas(path_authorization_rules=path_authorization_rules)


def apply_mcp_registry_deltas(
    *,
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    mcp_server_name_parsers = (RESOURCE_NAME_PARSER_MCP_SERVER_NAME,)

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
                    "update",
                    resource_name_parsers=mcp_server_name_parsers,
                ),
                (f"{prefix}/<path:name>/versions", "GET"): _mcp_servers_rule(
                    "get",
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
                    "get",
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
