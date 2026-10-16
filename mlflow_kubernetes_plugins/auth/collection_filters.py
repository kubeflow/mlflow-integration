"""Collection request/response filtering for fine-grained authorization."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import TYPE_CHECKING

from google.protobuf.json_format import ParseError
from mlflow.protos.model_registry_pb2 import SearchModelVersions, SearchRegisteredModels
from mlflow.protos.service_pb2 import (
    BatchGetTraceInfos,
    BatchGetTraces,
    ListScorers,
    SearchEvaluationDatasets,
    SearchExperiments,
    SearchTraces,
)
from mlflow.utils.proto_json_utils import parse_dict

from mlflow_kubernetes_plugins.auth.constants import (
    RESOURCE_DATASETS,
    RESOURCE_EXPERIMENTS,
    RESOURCE_MCP_SERVERS,
    RESOURCE_REGISTERED_MODELS,
)
from mlflow_kubernetes_plugins.auth.request_context import AuthorizationRequest
from mlflow_kubernetes_plugins.auth.resource_names import (
    ResourceNameResolutionError,
    _normalize_string,
    _resolve_experiment_name_from_experiment_id,
    _resolve_experiment_name_from_run_id,
    resolve_experiment_ids_from_names,
)

if TYPE_CHECKING:
    from mlflow_kubernetes_plugins.auth.authorizer import CollectionScope, KubernetesAuthorizer
    from mlflow_kubernetes_plugins.auth.core import _RequestIdentity


COLLECTION_POLICY_BROAD_ONLY = "broad_only"
COLLECTION_POLICY_GRAPHQL_FILTER = "graphql_filter"
COLLECTION_POLICY_REQUEST_EXPERIMENT_IDS = "request_filter_experiment_ids"
COLLECTION_POLICY_REQUEST_EXPERIMENT_ID = "request_filter_experiment_id"
COLLECTION_POLICY_REQUEST_RUN_IDS = "request_filter_run_ids"
COLLECTION_POLICY_REQUEST_TRACE_LOCATIONS = "request_filter_trace_locations"
COLLECTION_POLICY_REQUEST_AUTHORIZED_EXPERIMENT_IDS = "request_scope_authorized_experiment_ids"
COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS = "request_scope_search_experiments"
COLLECTION_POLICY_REQUEST_SEARCH_REGISTERED_MODELS = "request_scope_search_registered_models"
COLLECTION_POLICY_REQUEST_SEARCH_MODEL_VERSIONS = "request_scope_search_model_versions"
COLLECTION_POLICY_REQUEST_BATCH_GET_TRACES = "request_scope_batch_get_traces"
COLLECTION_POLICY_REQUEST_BATCH_GET_TRACE_INFOS = "request_scope_batch_get_trace_infos"
COLLECTION_POLICY_REQUEST_LIST_SCORERS = "request_scope_list_scorers"
COLLECTION_POLICY_REQUEST_SEARCH_DATASETS = "request_scope_search_datasets"
COLLECTION_POLICY_REQUEST_SEARCH_MCP_SERVERS = "request_scope_search_mcp_servers"
COLLECTION_POLICY_REQUEST_SEARCH_MCP_ACCESS_ENDPOINTS = "request_scope_search_mcp_access_endpoints"

_COLLECTION_REQUEST_MESSAGES = {
    COLLECTION_POLICY_REQUEST_AUTHORIZED_EXPERIMENT_IDS: SearchTraces,
    COLLECTION_POLICY_REQUEST_BATCH_GET_TRACE_INFOS: BatchGetTraceInfos,
    COLLECTION_POLICY_REQUEST_BATCH_GET_TRACES: BatchGetTraces,
    COLLECTION_POLICY_REQUEST_LIST_SCORERS: ListScorers,
    COLLECTION_POLICY_REQUEST_SEARCH_DATASETS: SearchEvaluationDatasets,
    COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS: SearchExperiments,
    COLLECTION_POLICY_REQUEST_SEARCH_REGISTERED_MODELS: SearchRegisteredModels,
    COLLECTION_POLICY_REQUEST_SEARCH_MODEL_VERSIONS: SearchModelVersions,
}

_EXPERIMENT_READ_RULE = (RESOURCE_EXPERIMENTS, "get")

_REQUEST_FILTER_POLICIES = {
    COLLECTION_POLICY_REQUEST_EXPERIMENT_IDS,
    COLLECTION_POLICY_REQUEST_EXPERIMENT_ID,
    COLLECTION_POLICY_REQUEST_RUN_IDS,
    COLLECTION_POLICY_REQUEST_TRACE_LOCATIONS,
    COLLECTION_POLICY_REQUEST_AUTHORIZED_EXPERIMENT_IDS,
    COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS,
    COLLECTION_POLICY_REQUEST_SEARCH_REGISTERED_MODELS,
    COLLECTION_POLICY_REQUEST_SEARCH_MODEL_VERSIONS,
    COLLECTION_POLICY_REQUEST_BATCH_GET_TRACES,
    COLLECTION_POLICY_REQUEST_BATCH_GET_TRACE_INFOS,
    COLLECTION_POLICY_REQUEST_LIST_SCORERS,
    COLLECTION_POLICY_REQUEST_SEARCH_DATASETS,
    COLLECTION_POLICY_REQUEST_SEARCH_MCP_SERVERS,
    COLLECTION_POLICY_REQUEST_SEARCH_MCP_ACCESS_ENDPOINTS,
}


def is_request_filter_policy(policy: str | None) -> bool:
    return policy in _REQUEST_FILTER_POLICIES


def is_graphql_collection_policy(policy: str | None) -> bool:
    return policy == COLLECTION_POLICY_GRAPHQL_FILTER


def _is_allowed_named_resource(
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    permission: tuple[str, str],
    resource_name: str,
) -> bool:
    resource, verb = permission
    return authorizer.is_allowed(
        identity,
        resource,
        verb,
        workspace_name,
        resource_name=resource_name,
    )


def _first_present_value(mapping: dict[str, object], *candidate_keys: str) -> object | None:
    """Return the first populated field across snake_case and camelCase payload variants."""
    for key in candidate_keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _can_read_experiment_id(
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    experiment_id: str,
) -> bool:
    try:
        experiment_name = _resolve_experiment_name_from_experiment_id(experiment_id)
    except ResourceNameResolutionError:
        return False
    return _is_allowed_named_resource(
        authorizer,
        identity,
        workspace_name,
        _EXPERIMENT_READ_RULE,
        experiment_name,
    )


def _can_read_run_id(
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    run_id: str,
) -> bool:
    try:
        experiment_name = _resolve_experiment_name_from_run_id(run_id)
    except ResourceNameResolutionError:
        return False
    return _is_allowed_named_resource(
        authorizer,
        identity,
        workspace_name,
        _EXPERIMENT_READ_RULE,
        experiment_name,
    )


def filter_readable_experiment_ids(
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    experiment_ids: list[str],
) -> list[str]:
    readable_ids: list[str] = []
    for experiment_id in experiment_ids:
        normalized_id = _normalize_string(experiment_id)
        if normalized_id is None:
            continue
        if _can_read_experiment_id(authorizer, identity, workspace_name, normalized_id):
            readable_ids.append(normalized_id)
    return readable_ids


def filter_readable_run_ids(
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    run_ids: list[str],
) -> list[str]:
    readable_ids: list[str] = []
    for run_id in run_ids:
        normalized_id = _normalize_string(run_id)
        if normalized_id is None:
            continue
        if _can_read_run_id(authorizer, identity, workspace_name, normalized_id):
            readable_ids.append(normalized_id)
    return readable_ids


def _request_values(request_context: AuthorizationRequest, key: str) -> list[str]:
    """Collect a request field from JSON body and query params.

    These request filters intentionally consider both body and query params because some MLflow
    routes still send identifiers in the query string even on mutating requests.
    """
    values: list[str] = []
    if isinstance(request_context.json_body, dict):
        body_value = request_context.json_body.get(key)
        if isinstance(body_value, list):
            values.extend(str(value) for value in body_value)
        elif body_value is not None:
            values.append(str(body_value))

    query_value = request_context.query_params.get(key)
    if isinstance(query_value, list):
        values.extend(str(value) for value in query_value)
    elif query_value is not None:
        values.append(str(query_value))

    return values


def _normalize_request_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [normalized for item in value if (normalized := _normalize_string(item))]
    if value is None:
        return []
    normalized = _normalize_string(value)
    return [normalized] if normalized is not None else []


def _normalize_request_value(value: object) -> str | None:
    values = _normalize_request_values(value)
    if not values:
        return None
    first_value = values[0]
    return first_value if all(value == first_value for value in values[1:]) else None


def _filter_request_experiment_ids(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    body_has_experiment_ids = (
        isinstance(request_context.json_body, dict)
        and "experiment_ids" in request_context.json_body
    )
    query_has_experiment_ids = "experiment_ids" in request_context.query_params
    if not body_has_experiment_ids and not query_has_experiment_ids:
        return request_context, False

    body_experiment_ids = (
        _normalize_request_values(request_context.json_body.get("experiment_ids"))
        if body_has_experiment_ids and isinstance(request_context.json_body, dict)
        else []
    )
    query_experiment_ids = (
        _normalize_request_values(request_context.query_params.get("experiment_ids"))
        if query_has_experiment_ids
        else []
    )
    readable_body_ids = filter_readable_experiment_ids(
        authorizer,
        identity,
        workspace_name,
        body_experiment_ids,
    )
    readable_query_ids = filter_readable_experiment_ids(
        authorizer,
        identity,
        workspace_name,
        query_experiment_ids,
    )
    if not readable_body_ids and not readable_query_ids:
        return request_context, False

    updated_request_context = request_context
    if body_has_experiment_ids and isinstance(request_context.json_body, dict):
        filtered_body = dict(request_context.json_body)
        filtered_body["experiment_ids"] = readable_body_ids
        updated_request_context = replace(updated_request_context, json_body=filtered_body)

    if query_has_experiment_ids:
        filtered_query_params = dict(request_context.query_params)
        if readable_query_ids:
            filtered_query_params["experiment_ids"] = readable_query_ids
        else:
            filtered_query_params.pop("experiment_ids", None)
        updated_request_context = replace(
            updated_request_context, query_params=filtered_query_params
        )

    return updated_request_context, True


def _filter_request_single_experiment_id(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    body_has_experiment_id = (
        isinstance(request_context.json_body, dict) and "experiment_id" in request_context.json_body
    )
    query_has_experiment_id = "experiment_id" in request_context.query_params
    if not body_has_experiment_id and not query_has_experiment_id:
        return request_context, False

    body_experiment_id = (
        _normalize_request_value(request_context.json_body.get("experiment_id"))
        if body_has_experiment_id and isinstance(request_context.json_body, dict)
        else None
    )
    query_experiment_id = (
        _normalize_request_value(request_context.query_params.get("experiment_id"))
        if query_has_experiment_id
        else None
    )

    if body_has_experiment_id and (
        body_experiment_id is None
        or not _can_read_experiment_id(authorizer, identity, workspace_name, body_experiment_id)
    ):
        return request_context, False
    if query_has_experiment_id and (
        query_experiment_id is None
        or not _can_read_experiment_id(authorizer, identity, workspace_name, query_experiment_id)
    ):
        return request_context, False

    return request_context, True


def _filter_request_run_ids(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    body_has_run_ids = (
        isinstance(request_context.json_body, dict) and "run_ids" in request_context.json_body
    )
    query_has_run_ids = "run_ids" in request_context.query_params
    if not body_has_run_ids and not query_has_run_ids:
        return request_context, False

    body_run_ids = (
        _normalize_request_values(request_context.json_body.get("run_ids"))
        if body_has_run_ids and isinstance(request_context.json_body, dict)
        else []
    )
    query_run_ids = (
        _normalize_request_values(request_context.query_params.get("run_ids"))
        if query_has_run_ids
        else []
    )
    readable_body_ids = filter_readable_run_ids(authorizer, identity, workspace_name, body_run_ids)
    readable_query_ids = filter_readable_run_ids(
        authorizer, identity, workspace_name, query_run_ids
    )
    if not readable_body_ids and not readable_query_ids:
        return request_context, False

    updated_request_context = request_context
    if body_has_run_ids and isinstance(request_context.json_body, dict):
        filtered_body = dict(request_context.json_body)
        filtered_body["run_ids"] = readable_body_ids
        updated_request_context = replace(updated_request_context, json_body=filtered_body)

    if query_has_run_ids:
        filtered_query_params = dict(request_context.query_params)
        if readable_query_ids:
            filtered_query_params["run_ids"] = readable_query_ids
        else:
            filtered_query_params.pop("run_ids", None)
        updated_request_context = replace(
            updated_request_context, query_params=filtered_query_params
        )

    return updated_request_context, True


def _filter_request_trace_locations(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    if not isinstance(request_context.json_body, dict):
        return request_context, False
    raw_locations = request_context.json_body.get("locations")
    if not isinstance(raw_locations, list):
        return request_context, False

    filtered_locations: list[dict[str, object]] = []
    for location in raw_locations:
        if not isinstance(location, dict):
            continue
        mlflow_location = _first_present_value(location, "mlflow_experiment", "mlflowExperiment")
        if not isinstance(mlflow_location, dict):
            continue
        experiment_id = _normalize_string(
            _first_present_value(mlflow_location, "experiment_id", "experimentId")
        )
        if experiment_id is None:
            continue
        if _can_read_experiment_id(authorizer, identity, workspace_name, experiment_id):
            filtered_locations.append(location)

    if not filtered_locations:
        return request_context, False

    filtered_body = dict(request_context.json_body)
    filtered_body["locations"] = filtered_locations
    return replace(request_context, json_body=filtered_body), True


def _filter_request_authorized_experiment_ids(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    *,
    scope: "CollectionScope | None" = None,
) -> tuple[AuthorizationRequest, bool]:
    if scope is None:
        scope = authorizer.discover_collection_scope(identity, RESOURCE_EXPERIMENTS, workspace_name)
    if scope.broad:
        return request_context, True
    if not scope.names:
        return request_context, False

    try:
        allowed_ids = set(resolve_experiment_ids_from_names(scope.names))
    except ResourceNameResolutionError:
        return request_context, False
    if not allowed_ids:
        return request_context, False

    body = request_context.json_body
    query = request_context.query_params
    # MLflow accepts protobuf JSON aliases in request bodies, but its GET parser
    # recognizes protobuf field names only.
    body_id_keys = ("experiment_ids", "experimentIds")
    query_id_keys = ("experiment_ids",)
    body_keys = [key for key in body_id_keys if isinstance(body, dict) and key in body]
    query_keys = [key for key in query_id_keys if key in query]

    def request_ids(value: object, *, allow_scalar: bool) -> set[str] | None:
        if allow_scalar and isinstance(value, str):
            return {value} if value else None
        if (
            isinstance(value, list)
            and value
            and all(isinstance(item, str) and item for item in value)
        ):
            return set(value)
        return None

    selected_ids = allowed_ids
    for key in body_keys:
        assert isinstance(body, dict)
        body_ids = request_ids(body[key], allow_scalar=False)
        if body_ids is None:
            return request_context, False
        selected_ids &= body_ids
    for key in query_keys:
        query_ids = request_ids(query[key], allow_scalar=True)
        if query_ids is None:
            return request_context, False
        selected_ids &= query_ids
    if not selected_ids:
        return request_context, False

    narrowed_ids = sorted(selected_ids)
    method = request_context.method.upper()
    if method == "POST" and not isinstance(body, dict):
        return request_context, False
    if body_keys or method == "POST":
        assert isinstance(body, dict)
        narrowed_body = {key: value for key, value in body.items() if key not in body_id_keys}
        narrowed_body["experiment_ids"] = narrowed_ids
        request_context = replace(request_context, json_body=narrowed_body)
    if query_keys or method != "POST":
        narrowed_query = {key: value for key, value in query.items() if key not in query_id_keys}
        narrowed_query["experiment_ids"] = narrowed_ids
        request_context = replace(request_context, query_params=narrowed_query)
    return request_context, True


def _filter_request_list_scorers(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    if request_context.method.upper() != "GET":
        return request_context, False
    query = request_context.query_params
    # ListScorers is a GET endpoint. MLflow's GET parser recognizes protobuf
    # field names only, not their JSON camelCase aliases. Do not authorize an
    # unmodified request based on an alias MLflow would ignore.
    if "experiment_id" in query and "experiment_ids" in query:
        return request_context, False
    if "experiment_id" in query:
        experiment_id = _normalize_string(query["experiment_id"])
        if experiment_id is None:
            return request_context, False
        return request_context, _can_read_experiment_id(
            authorizer, identity, workspace_name, experiment_id
        )

    scope = authorizer.discover_collection_scope(identity, RESOURCE_EXPERIMENTS, workspace_name)
    if scope.broad:
        return request_context, True
    return _filter_request_authorized_experiment_ids(
        request_context, authorizer, identity, workspace_name, scope=scope
    )


def _quote_filter_literal(value: str) -> str:
    """Quote an MLflow equality value without applying Python escape sequences.

    Equality strips enclosing quotes without unescaping their contents. IN lists
    instead use Python literal decoding, so their elements must still use repr().
    Names containing both quote delimiters cannot be represented in equality.
    """
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value:
        return '"' + value + '"'
    raise ValueError("Resource name contains both MLflow string quote delimiters.")


def _filter_request_search_datasets(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    scope = authorizer.discover_collection_scope(identity, RESOURCE_DATASETS, workspace_name)
    if scope.broad:
        return request_context, True
    if not scope.names:
        return request_context, False
    method = request_context.method.upper()
    body = request_context.json_body
    if method not in {"GET", "POST"} or (method == "POST" and not isinstance(body, dict)):
        return request_context, False

    if method == "POST" and isinstance(body, dict) and "filterString" in body:
        if "filter_string" in body:
            return request_context, False
        body = dict(body)
        body["filter_string"] = body.pop("filterString")

    if len(scope.names) == 1:
        try:
            quoted_name = _quote_filter_literal(scope.names[0])
        except ValueError:
            return request_context, False
        scope_filter = f"name = {quoted_name}"
        comparator = "="
        expected_value: str | tuple[str, ...] = scope.names[0]
    else:
        scope_filter = "name IN (" + ", ".join(repr(name) for name in scope.names) + ")"
        comparator = "IN"
        expected_value = scope.names

    caller_filters: list[str] = []
    for source in (body, request_context.query_params):
        if not isinstance(source, dict) or "filter_string" not in source:
            continue
        value = source["filter_string"]
        if not isinstance(value, str):
            return request_context, False
        if value.strip():
            caller_filters.append(value.strip())
    narrowed_filter = " AND ".join([*caller_filters, scope_filter])
    try:
        from mlflow.utils.search_utils import SearchEvaluationDatasetsUtils

        parsed = SearchEvaluationDatasetsUtils.parse_search_filter(narrowed_filter)
        expected_scope = {
            "type": "attribute",
            "key": "name",
            "comparator": comparator,
            "value": expected_value,
        }
        if not parsed or parsed[-1] != expected_scope:
            return request_context, False
    except Exception:
        return request_context, False

    if method == "POST":
        assert isinstance(body, dict)
        return replace(request_context, json_body={**body, "filter_string": narrowed_filter}), True
    return replace(
        request_context,
        query_params={**request_context.query_params, "filter_string": narrowed_filter},
    ), True


def _filter_request_search_mcp(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    *,
    access_endpoints: bool = False,
) -> tuple[AuthorizationRequest, bool]:
    scope = authorizer.discover_collection_scope(identity, RESOURCE_MCP_SERVERS, workspace_name)
    if scope.broad:
        return request_context, True
    if not scope.names or request_context.method.upper() != "GET":
        return request_context, False
    key = "server_name" if access_endpoints else "name"
    if len(scope.names) == 1:
        try:
            quoted_name = _quote_filter_literal(scope.names[0])
        except ValueError:
            return request_context, False
        scope_filter = f"{key} = {quoted_name}"
        comparator = "="
        expected_value: str | tuple[str, ...] = scope.names[0]
    else:
        scope_filter = f"{key} IN (" + ", ".join(repr(name) for name in scope.names) + ")"
        comparator = "IN"
        expected_value = scope.names

    existing_filter = request_context.query_params.get("filter_string", "")
    if not isinstance(existing_filter, str):
        return request_context, False
    existing_filter = existing_filter.strip()
    narrowed_filter = f"{existing_filter} AND {scope_filter}" if existing_filter else scope_filter
    try:
        from mlflow.utils.search_utils import SearchMCPAccessEndpointUtils, SearchMCPServerUtils

        parser = SearchMCPAccessEndpointUtils if access_endpoints else SearchMCPServerUtils
        parsed = parser.parse_search_filter(narrowed_filter)
        if not parsed or parsed[-1] != {
            "type": "attribute",
            "key": key,
            "comparator": comparator,
            "value": expected_value,
        }:
            return request_context, False
    except Exception:
        return request_context, False
    return replace(
        request_context,
        query_params={**request_context.query_params, "filter_string": narrowed_filter},
    ), True


def _filter_request_search_experiments(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    scope = authorizer.discover_collection_scope(identity, RESOURCE_EXPERIMENTS, workspace_name)
    if scope.broad:
        return request_context, True
    if not scope.names:
        return request_context, False
    if len(scope.names) == 1:
        try:
            quoted_name = _quote_filter_literal(scope.names[0])
        except ValueError:
            return request_context, False
        # Equality is supported by released MLflow and needs no name-to-ID lookup.
        scope_filter = f"name = {quoted_name}"
        expected_scope = {
            "type": "attribute",
            "key": "name",
            "comparator": "=",
            "value": scope.names[0],
        }
    else:
        try:
            experiment_ids = sorted(set(resolve_experiment_ids_from_names(scope.names)))
        except ResourceNameResolutionError:
            return request_context, False
        # SQL-backed MLflow experiment IDs are decimal strings. Restrict the injected
        # literal grammar even though the IDs came from the tracking store.
        if not experiment_ids or any(
            not re.fullmatch(r"[0-9]+", value) for value in experiment_ids
        ):
            return request_context, False
        scope_filter = (
            "experiment_id IN (" + ", ".join(f"'{value}'" for value in experiment_ids) + ")"
        )
        expected_scope = {
            "type": "attribute",
            "key": "experiment_id",
            "comparator": "IN",
            "value": tuple(experiment_ids),
        }

    body = request_context.json_body
    method = request_context.method.upper()
    if method not in {"GET", "POST"} or (method == "POST" and not isinstance(body, dict)):
        return request_context, False
    filters: list[str] = []
    for source in (body, request_context.query_params):
        if not isinstance(source, dict) or "filter" not in source:
            continue
        value = source["filter"]
        if not isinstance(value, str):
            return request_context, False
        if value.strip():
            filters.append(value.strip())
    narrowed_filter = " AND ".join([*filters, scope_filter])
    try:
        from mlflow.utils.search_utils import SearchExperimentsUtils

        parsed = SearchExperimentsUtils.parse_search_filter(narrowed_filter)
        if not parsed or parsed[-1] != expected_scope:
            return request_context, False
    except Exception:
        return request_context, False
    if method == "POST":
        assert isinstance(body, dict)
        request_context = replace(request_context, json_body={**body, "filter": narrowed_filter})
    else:
        request_context = replace(
            request_context,
            query_params={**request_context.query_params, "filter": narrowed_filter},
        )
    return request_context, True


def _filter_request_registered_model_search(
    request_context: AuthorizationRequest,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    *,
    model_versions: bool,
) -> tuple[AuthorizationRequest, bool]:
    scope = authorizer.discover_collection_scope(
        identity, RESOURCE_REGISTERED_MODELS, workspace_name
    )
    if scope.broad:
        return request_context, True
    if not scope.names or request_context.method.upper() != "GET":
        return request_context, False

    if len(scope.names) == 1:
        try:
            quoted_name = _quote_filter_literal(scope.names[0])
        except ValueError:
            return request_context, False
        scope_filter = f"name = {quoted_name}"
        comparator = "="
        expected_value: str | tuple[str, ...] = scope.names[0]
    else:
        scope_filter = "name IN (" + ", ".join(repr(name) for name in scope.names) + ")"
        comparator = "IN"
        expected_value = scope.names

    existing_filter = request_context.query_params.get("filter", "")
    if not isinstance(existing_filter, str):
        return request_context, False
    existing_filter = existing_filter.strip()
    narrowed_filter = f"{existing_filter} AND {scope_filter}" if existing_filter else scope_filter
    try:
        from mlflow.utils.search_utils import SearchModelUtils, SearchModelVersionUtils

        parser = SearchModelVersionUtils if model_versions else SearchModelUtils
        parsed = parser.parse_search_filter(narrowed_filter)
        if not parsed or parsed[-1] != {
            "type": "attribute",
            "key": "name",
            "comparator": comparator,
            "value": expected_value,
        }:
            return request_context, False
    except Exception:
        # An older or incomplete MLflow build cannot safely express this scope.
        return request_context, False
    return replace(
        request_context,
        query_params={**request_context.query_params, "filter": narrowed_filter},
    ), True


def _normalize_collection_request(
    request_context: AuthorizationRequest, policy: str
) -> tuple[AuthorizationRequest, bool]:
    body = request_context.json_body
    if isinstance(body, str):
        # Match MLflow's one additional decode for legacy JSON-string bodies.
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return request_context, False
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return request_context, False
        request_context = replace(request_context, json_body=body)

    if (
        request_context.method.upper() != "GET"
        or request_context.query_params
        or not isinstance(body, dict)
    ):
        return request_context, True

    # MLflow reads a GET body only when there are no query parameters. Move
    # its complete protobuf input to the query before adding an auth scope;
    # handlers also inspect query presence for experiment_ids restrictions.
    message = _COLLECTION_REQUEST_MESSAGES[policy]()
    for field in message.DESCRIPTOR.fields:
        if field.name != field.json_name and field.name in body and field.json_name in body:
            return request_context, False
    try:
        parse_dict(body, message)
    except (ParseError, TypeError, ValueError):
        return request_context, False
    query = {}
    for field in message.DESCRIPTOR.fields:
        if field.name in body or field.json_name in body:
            value = getattr(message, field.name)
            try:
                is_repeated = field.is_repeated
            except AttributeError:
                is_repeated = field.label == field.LABEL_REPEATED
            query[field.name] = list(value) if is_repeated else value
    return replace(request_context, json_body=None, query_params=query), True


def apply_request_collection_filter(
    request_context: AuthorizationRequest,
    policy: str | None,
    *,
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
) -> tuple[AuthorizationRequest, bool]:
    """Narrow a collection request to resources the caller can access.

    Returns ``(updated_request_context, applied)`` where *applied* is ``True``
    when the filter found identifiers in the request and narrowed them to the
    subset the caller is authorized for.
    """
    if policy in _COLLECTION_REQUEST_MESSAGES:
        assert policy is not None
        request_context, normalized = _normalize_collection_request(request_context, policy)
        if not normalized:
            return request_context, False
    if policy == COLLECTION_POLICY_REQUEST_EXPERIMENT_IDS:
        return _filter_request_experiment_ids(request_context, authorizer, identity, workspace_name)
    if policy == COLLECTION_POLICY_REQUEST_EXPERIMENT_ID:
        return _filter_request_single_experiment_id(
            request_context, authorizer, identity, workspace_name
        )
    if policy == COLLECTION_POLICY_REQUEST_RUN_IDS:
        return _filter_request_run_ids(request_context, authorizer, identity, workspace_name)
    if policy == COLLECTION_POLICY_REQUEST_TRACE_LOCATIONS:
        return _filter_request_trace_locations(
            request_context, authorizer, identity, workspace_name
        )
    if policy == COLLECTION_POLICY_REQUEST_AUTHORIZED_EXPERIMENT_IDS:
        return _filter_request_authorized_experiment_ids(
            request_context, authorizer, identity, workspace_name
        )
    if policy in {
        COLLECTION_POLICY_REQUEST_BATCH_GET_TRACES,
        COLLECTION_POLICY_REQUEST_BATCH_GET_TRACE_INFOS,
    }:
        scope = authorizer.discover_collection_scope(identity, RESOURCE_EXPERIMENTS, workspace_name)
        if scope.broad:
            return request_context, True
        return _filter_request_authorized_experiment_ids(
            request_context, authorizer, identity, workspace_name, scope=scope
        )
    if policy == COLLECTION_POLICY_REQUEST_LIST_SCORERS:
        return _filter_request_list_scorers(request_context, authorizer, identity, workspace_name)
    if policy == COLLECTION_POLICY_REQUEST_SEARCH_DATASETS:
        return _filter_request_search_datasets(
            request_context, authorizer, identity, workspace_name
        )
    if policy == COLLECTION_POLICY_REQUEST_SEARCH_MCP_SERVERS:
        return _filter_request_search_mcp(request_context, authorizer, identity, workspace_name)
    if policy == COLLECTION_POLICY_REQUEST_SEARCH_MCP_ACCESS_ENDPOINTS:
        return _filter_request_search_mcp(
            request_context, authorizer, identity, workspace_name, access_endpoints=True
        )
    if policy == COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS:
        return _filter_request_search_experiments(
            request_context, authorizer, identity, workspace_name
        )
    if policy == COLLECTION_POLICY_REQUEST_SEARCH_REGISTERED_MODELS:
        return _filter_request_registered_model_search(
            request_context, authorizer, identity, workspace_name, model_versions=False
        )
    if policy == COLLECTION_POLICY_REQUEST_SEARCH_MODEL_VERSIONS:
        return _filter_request_registered_model_search(
            request_context, authorizer, identity, workspace_name, model_versions=True
        )
    return request_context, False


def filter_graphql_experiment_ids(
    authorizer: "KubernetesAuthorizer",
    identity: "_RequestIdentity",
    workspace_name: str,
    experiment_ids: list[str],
) -> list[str]:
    return filter_readable_experiment_ids(authorizer, identity, workspace_name, experiment_ids)


__all__ = [
    "COLLECTION_POLICY_BROAD_ONLY",
    "COLLECTION_POLICY_GRAPHQL_FILTER",
    "COLLECTION_POLICY_REQUEST_EXPERIMENT_ID",
    "COLLECTION_POLICY_REQUEST_EXPERIMENT_IDS",
    "COLLECTION_POLICY_REQUEST_RUN_IDS",
    "COLLECTION_POLICY_REQUEST_TRACE_LOCATIONS",
    "COLLECTION_POLICY_REQUEST_AUTHORIZED_EXPERIMENT_IDS",
    "COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS",
    "COLLECTION_POLICY_REQUEST_SEARCH_REGISTERED_MODELS",
    "COLLECTION_POLICY_REQUEST_SEARCH_MODEL_VERSIONS",
    "COLLECTION_POLICY_REQUEST_BATCH_GET_TRACES",
    "COLLECTION_POLICY_REQUEST_BATCH_GET_TRACE_INFOS",
    "COLLECTION_POLICY_REQUEST_LIST_SCORERS",
    "COLLECTION_POLICY_REQUEST_SEARCH_DATASETS",
    "COLLECTION_POLICY_REQUEST_SEARCH_MCP_SERVERS",
    "COLLECTION_POLICY_REQUEST_SEARCH_MCP_ACCESS_ENDPOINTS",
    "apply_request_collection_filter",
    "filter_graphql_experiment_ids",
    "filter_readable_run_ids",
    "is_graphql_collection_policy",
    "is_request_filter_policy",
]
