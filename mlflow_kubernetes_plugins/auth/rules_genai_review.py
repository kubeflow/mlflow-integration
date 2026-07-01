"""Authorization rules for MLflow GenAI labeling and review queue APIs."""

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
from mlflow_kubernetes_plugins.auth.collection_filters import (
    COLLECTION_POLICY_REQUEST_EXPERIMENT_ID,
)
from mlflow_kubernetes_plugins.auth.resource_names import (
    RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,
    RESOURCE_NAME_PARSER_LABEL_SCHEMA_ID_TO_EXPERIMENT_NAME,
    RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,
)
from mlflow_kubernetes_plugins.auth.rules import AuthorizationRule, _experiments_rule


def _add_request_rule(
    request_authorization_rules: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]],
    request_class: type | None,
    rule: AuthorizationRule | tuple[AuthorizationRule, ...],
) -> None:
    if request_class is not None:
        request_authorization_rules[request_class] = rule


def apply_genai_review_deltas(
    *,
    request_authorization_rules: dict[type, AuthorizationRule | tuple[AuthorizationRule, ...]],
    path_authorization_rules: dict[
        tuple[str, str], AuthorizationRule | tuple[AuthorizationRule, ...]
    ],
) -> None:
    _add_request_rule(
        request_authorization_rules,
        CreateLabelSchema,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        GetLabelSchema,
        _experiments_rule(
            "get",
            resource_name_parsers=(RESOURCE_NAME_PARSER_LABEL_SCHEMA_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        GetLabelSchemaByName,
        _experiments_rule(
            "get",
            resource_name_parsers=(RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        ListLabelSchemas,
        _experiments_rule(
            "list",
            collection_policy=COLLECTION_POLICY_REQUEST_EXPERIMENT_ID,
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        UpdateLabelSchema,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_LABEL_SCHEMA_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        DeleteLabelSchema,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_LABEL_SCHEMA_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        CreateReviewQueue,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        GetOrCreateUserQueue,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        GetReviewQueue,
        _experiments_rule(
            "get",
            resource_name_parsers=(RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        GetReviewQueueByName,
        _experiments_rule(
            "get",
            resource_name_parsers=(RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        ListReviewQueues,
        _experiments_rule(
            "list",
            collection_policy=COLLECTION_POLICY_REQUEST_EXPERIMENT_ID,
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        UpdateReviewQueue,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        DeleteReviewQueue,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        AddItemsToReviewQueue,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        RemoveItemsFromReviewQueue,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        ListReviewQueueItems,
        _experiments_rule(
            "get",
            resource_name_parsers=(RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    _add_request_rule(
        request_authorization_rules,
        SetReviewQueueItemStatus,
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_REVIEW_QUEUE_ID_TO_EXPERIMENT_NAME,),
        ),
    )
    path_authorization_rules[("/ajax-api/3.0/mlflow/genai/evaluate/invoke", "POST")] = (
        _experiments_rule(
            "update",
            resource_name_parsers=(RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,),
        )
    )
