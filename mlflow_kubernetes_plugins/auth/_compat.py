"""Compatibility helpers for MLflow-version-dependent auth surfaces."""

from __future__ import annotations

import importlib

import mlflow
from mlflow.protos import mlflow_artifacts_pb2 as artifacts_pb2
from mlflow.protos import service_pb2 as service_pb2_mod
from packaging.version import Version

MLFLOW_VERSION = Version(mlflow.__version__)
HAS_MLFLOW_3_11_AUTH_SURFACE = MLFLOW_VERSION >= Version("3.11.0.dev0")
HAS_MLFLOW_3_12_AUTH_SURFACE = MLFLOW_VERSION >= Version("3.12.0.dev0")
HAS_MLFLOW_3_13_AUTH_SURFACE = MLFLOW_VERSION >= Version("3.13.0.dev0")
HAS_MLFLOW_3_14_AUTH_SURFACE = MLFLOW_VERSION >= Version("3.14.0.dev0")

if HAS_MLFLOW_3_11_AUTH_SURFACE:
    GetPresignedDownloadUrl = artifacts_pb2.GetPresignedDownloadUrl
    # `issues_pb2` is absent on MLflow 3.10, so this module import must stay conditional even
    # though the service protobuf module itself exists across both supported minor lines.
    issues_pb2 = importlib.import_module("mlflow.protos.issues_pb2")
    CreateIssue = issues_pb2.CreateIssue
    GetIssue = issues_pb2.GetIssue
    SearchIssues = issues_pb2.SearchIssues
    UpdateIssue = issues_pb2.UpdateIssue
    BatchGetTraceInfos = service_pb2_mod.BatchGetTraceInfos
    CreateGatewayBudgetPolicy = service_pb2_mod.CreateGatewayBudgetPolicy
    DeleteGatewayBudgetPolicy = service_pb2_mod.DeleteGatewayBudgetPolicy
    GetGatewayBudgetPolicy = service_pb2_mod.GetGatewayBudgetPolicy
    ListGatewayBudgetPolicies = service_pb2_mod.ListGatewayBudgetPolicies
    ListGatewayBudgetWindows = service_pb2_mod.ListGatewayBudgetWindows
    UpdateGatewayBudgetPolicy = service_pb2_mod.UpdateGatewayBudgetPolicy
else:  # pragma: no cover - exercised via MLflow version matrix
    GetPresignedDownloadUrl = None
    CreateIssue = GetIssue = SearchIssues = UpdateIssue = None
    BatchGetTraceInfos = None
    CreateGatewayBudgetPolicy = None
    DeleteGatewayBudgetPolicy = None
    GetGatewayBudgetPolicy = None
    ListGatewayBudgetPolicies = None
    ListGatewayBudgetWindows = None
    UpdateGatewayBudgetPolicy = None

if HAS_MLFLOW_3_12_AUTH_SURFACE:
    CreatePresignedUploadUrl = service_pb2_mod.CreatePresignedUploadUrl
    CreateGatewayGuardrail = service_pb2_mod.CreateGatewayGuardrail
    GetGatewayGuardrail = service_pb2_mod.GetGatewayGuardrail
    DeleteGatewayGuardrail = service_pb2_mod.DeleteGatewayGuardrail
    ListGatewayGuardrails = service_pb2_mod.ListGatewayGuardrails
    AddGuardrailToEndpoint = service_pb2_mod.AddGuardrailToEndpoint
    RemoveGuardrailFromEndpoint = service_pb2_mod.RemoveGuardrailFromEndpoint
    ListEndpointGuardrailConfigs = service_pb2_mod.ListEndpointGuardrailConfigs
    UpdateEndpointGuardrailConfig = service_pb2_mod.UpdateEndpointGuardrailConfig
else:  # pragma: no cover - exercised via MLflow version matrix
    CreatePresignedUploadUrl = None
    CreateGatewayGuardrail = None
    GetGatewayGuardrail = None
    DeleteGatewayGuardrail = None
    ListGatewayGuardrails = None
    AddGuardrailToEndpoint = None
    RemoveGuardrailFromEndpoint = None
    ListEndpointGuardrailConfigs = None
    UpdateEndpointGuardrailConfig = None

if HAS_MLFLOW_3_14_AUTH_SURFACE:
    label_schemas_pb2 = importlib.import_module("mlflow.protos.label_schemas_pb2")
    CreateLabelSchema = label_schemas_pb2.CreateLabelSchema
    DeleteLabelSchema = label_schemas_pb2.DeleteLabelSchema
    GetLabelSchema = label_schemas_pb2.GetLabelSchema
    GetLabelSchemaByName = label_schemas_pb2.GetLabelSchemaByName
    ListLabelSchemas = label_schemas_pb2.ListLabelSchemas
    UpdateLabelSchema = label_schemas_pb2.UpdateLabelSchema
    review_queues_pb2 = importlib.import_module("mlflow.protos.review_queues_pb2")
    AddItemsToReviewQueue = review_queues_pb2.AddItemsToReviewQueue
    CreateReviewQueue = review_queues_pb2.CreateReviewQueue
    DeleteReviewQueue = review_queues_pb2.DeleteReviewQueue
    GetOrCreateUserQueue = review_queues_pb2.GetOrCreateUserQueue
    GetReviewQueue = review_queues_pb2.GetReviewQueue
    GetReviewQueueByName = review_queues_pb2.GetReviewQueueByName
    ListReviewQueueItems = review_queues_pb2.ListReviewQueueItems
    ListReviewQueues = review_queues_pb2.ListReviewQueues
    RemoveItemsFromReviewQueue = review_queues_pb2.RemoveItemsFromReviewQueue
    SetReviewQueueItemStatus = review_queues_pb2.SetReviewQueueItemStatus
    UpdateReviewQueue = review_queues_pb2.UpdateReviewQueue
else:  # pragma: no cover - exercised via MLflow version matrix
    CreateLabelSchema = DeleteLabelSchema = GetLabelSchema = None
    GetLabelSchemaByName = ListLabelSchemas = UpdateLabelSchema = None
    AddItemsToReviewQueue = CreateReviewQueue = DeleteReviewQueue = None
    GetOrCreateUserQueue = GetReviewQueue = GetReviewQueueByName = None
    ListReviewQueueItems = ListReviewQueues = None
    RemoveItemsFromReviewQueue = SetReviewQueueItemStatus = UpdateReviewQueue = None

__all__ = [
    "AddGuardrailToEndpoint",
    "AddItemsToReviewQueue",
    "BatchGetTraceInfos",
    "CreateGatewayBudgetPolicy",
    "CreateGatewayGuardrail",
    "CreateIssue",
    "CreateLabelSchema",
    "CreatePresignedUploadUrl",
    "CreateReviewQueue",
    "DeleteGatewayBudgetPolicy",
    "DeleteGatewayGuardrail",
    "DeleteLabelSchema",
    "DeleteReviewQueue",
    "GetGatewayBudgetPolicy",
    "GetGatewayGuardrail",
    "GetIssue",
    "GetLabelSchema",
    "GetLabelSchemaByName",
    "GetOrCreateUserQueue",
    "GetPresignedDownloadUrl",
    "GetReviewQueue",
    "GetReviewQueueByName",
    "HAS_MLFLOW_3_11_AUTH_SURFACE",
    "HAS_MLFLOW_3_12_AUTH_SURFACE",
    "HAS_MLFLOW_3_13_AUTH_SURFACE",
    "HAS_MLFLOW_3_14_AUTH_SURFACE",
    "ListEndpointGuardrailConfigs",
    "ListGatewayBudgetPolicies",
    "ListGatewayBudgetWindows",
    "ListGatewayGuardrails",
    "ListLabelSchemas",
    "ListReviewQueueItems",
    "ListReviewQueues",
    "MLFLOW_VERSION",
    "RemoveGuardrailFromEndpoint",
    "RemoveItemsFromReviewQueue",
    "SearchIssues",
    "SetReviewQueueItemStatus",
    "UpdateEndpointGuardrailConfig",
    "UpdateGatewayBudgetPolicy",
    "UpdateIssue",
    "UpdateLabelSchema",
    "UpdateReviewQueue",
]
