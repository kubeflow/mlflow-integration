"""MLflow 3.14 authorization deltas layered on top of the earlier tables."""

from __future__ import annotations

from mlflow_kubernetes_plugins.auth._compat import (
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
from mlflow_kubernetes_plugins.auth.resource_names import (
    RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,
    RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,
)
from mlflow_kubernetes_plugins.auth.rules import (
    AuthorizationRule,
    _experiments_rule,
    _gateway_endpoints_use_rule,
)


def apply_v3_14_deltas(
    *,
    request_authorization_rules: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]],
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    experiment_id_parsers = (RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,)

    # --- Label Schemas ---
    # Endpoints with experiment_id get experiment-level resourceName checks.
    # ID-only endpoints (schema_id) fall back to workspace-level access because no
    # tracking store API exists to resolve schema_id → experiment.
    request_authorization_rules.update(
        {
            CreateLabelSchema: _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            GetLabelSchema: _experiments_rule("get"),
            GetLabelSchemaByName: _experiments_rule(
                "get", resource_name_parsers=experiment_id_parsers
            ),
            ListLabelSchemas: _experiments_rule(
                "get", resource_name_parsers=experiment_id_parsers
            ),
            UpdateLabelSchema: _experiments_rule("update"),
            DeleteLabelSchema: _experiments_rule("update"),
        }
    )

    # --- Review Queues ---
    # Same ID-resolution convention: queue_id-only endpoints are workspace-scoped.
    request_authorization_rules.update(
        {
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
            ListReviewQueues: _experiments_rule(
                "get", resource_name_parsers=experiment_id_parsers
            ),
            UpdateReviewQueue: _experiments_rule("update"),
            DeleteReviewQueue: _experiments_rule("update"),
            AddItemsToReviewQueue: _experiments_rule("update"),
            RemoveItemsFromReviewQueue: _experiments_rule("update"),
            ListReviewQueueItems: _experiments_rule("get"),
            SetReviewQueueItemStatus: _experiments_rule("update"),
        }
    )

    # --- Path-based endpoints ---
    path_authorization_rules.update(
        {
            # UI-triggered evaluation run; experiment_id is a required JSON body field.
            ("/ajax-api/3.0/mlflow/genai/evaluate/invoke", "POST"): _experiments_rule(
                "update", resource_name_parsers=experiment_id_parsers
            ),
            # OpenAI /responses/compact passthrough route added in 3.14.
            ("/gateway/openai/v1/responses/compact", "POST"): _gateway_endpoints_use_rule(
                resource_name_parsers=(RESOURCE_NAME_PARSER_GATEWAY_PROXY_ENDPOINT_NAME,),
            ),
        }
    )
