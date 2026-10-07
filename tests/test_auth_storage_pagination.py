"""Storage-backed pagination regression tests for request-side collection scoping."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from mlflow.tracking import MlflowClient
from mlflow_kubernetes_plugins.auth.authorizer import CollectionScope
from mlflow_kubernetes_plugins.auth.collection_filters import (
    COLLECTION_POLICY_REQUEST_SEARCH_DATASETS,
    COLLECTION_POLICY_REQUEST_SEARCH_MCP_ACCESS_ENDPOINTS,
    apply_request_collection_filter,
)
from mlflow_kubernetes_plugins.auth.core import _RequestIdentity
from mlflow_kubernetes_plugins.auth.request_context import AuthorizationRequest


def _sqlite_client(tmp_path) -> MlflowClient:
    return MlflowClient(tracking_uri=f"sqlite:///{tmp_path}/mlflow.db")


def _request_context(path: str) -> AuthorizationRequest:
    return AuthorizationRequest(
        authorization_header=None,
        forwarded_access_token=None,
        remote_user_header_value=None,
        remote_groups_header_value=None,
        path=path,
        method="GET",
        workspace="team-a",
    )


def _scoped_filter(
    path: str, policy: str, allowed_names: tuple[str, ...], unsupported_message: str
) -> str:
    authorizer = Mock()
    authorizer.discover_collection_scope.return_value = CollectionScope(names=allowed_names)
    updated, applied = apply_request_collection_filter(
        _request_context(path),
        policy,
        authorizer=authorizer,
        identity=_RequestIdentity(token="token"),
        workspace_name="team-a",
    )
    if not applied:
        pytest.skip(unsupported_message)

    filter_string = updated.query_params["filter_string"]
    assert isinstance(filter_string, str)
    return filter_string


def _collect_paginated_names(search_page, name_of) -> list[str]:
    collected: list[str] = []
    page_token = None
    while True:
        page = search_page(page_token)
        collected.extend(name_of(item) for item in page)
        page_token = page.token
        if not page_token:
            return collected


def test_search_evaluation_datasets_scoped_filter_paginates_without_underfill(tmp_path):
    client = _sqlite_client(tmp_path)
    experiment_id = client.create_experiment("exp-a")

    allowed_names: list[str] = []
    forbidden_names: list[str] = []
    for index in range(9):
        name = f"dataset-{index:02d}"
        client.create_dataset(name=name, experiment_id=experiment_id)
        # Interleave readable and unreadable datasets so a page boundary falls
        # inside a run of each - the shape that underfilled pages under
        # response-side filtering.
        (allowed_names if index % 2 == 0 else forbidden_names).append(name)

    filter_string = _scoped_filter(
        "/api/3.0/mlflow/datasets/search",
        COLLECTION_POLICY_REQUEST_SEARCH_DATASETS,
        tuple(sorted(allowed_names)),
        "Installed MLflow version cannot express a multi-name dataset scope.",
    )
    collected = _collect_paginated_names(
        lambda page_token: client.search_datasets(
            filter_string=filter_string, max_results=2, page_token=page_token
        ),
        lambda dataset: dataset.name,
    )

    assert sorted(collected) == sorted(allowed_names)
    assert not set(collected) & set(forbidden_names)


def test_search_evaluation_datasets_scope_is_independent_of_experiment_associations(tmp_path):
    """Dataset access is scoped by name, regardless of experiment associations."""
    client = _sqlite_client(tmp_path)
    exp_a = client.create_experiment("exp-a")
    exp_b = client.create_experiment("exp-b")

    client.create_dataset(name="dataset-no-experiments")
    client.create_dataset(name="dataset-multi-experiments", experiment_id=[exp_a, exp_b])
    client.create_dataset(name="dataset-forbidden-no-experiments")
    client.create_dataset(name="dataset-forbidden-multi-experiments", experiment_id=[exp_a, exp_b])

    allowed_names = ("dataset-multi-experiments", "dataset-no-experiments")
    filter_string = _scoped_filter(
        "/api/3.0/mlflow/datasets/search",
        COLLECTION_POLICY_REQUEST_SEARCH_DATASETS,
        allowed_names,
        "Installed MLflow version cannot express a multi-name dataset scope.",
    )
    page = client.search_datasets(filter_string=filter_string, max_results=10)

    assert sorted(dataset.name for dataset in page) == sorted(allowed_names)


def test_search_mcp_access_endpoints_scoped_filter_paginates_without_underfill(tmp_path):
    mcp_server = pytest.importorskip(
        "mlflow.entities.mcp_server",
        reason="Installed MLflow version does not expose the MCP registry API.",
    )
    MCPStatus = mcp_server.MCPStatus
    client = _sqlite_client(tmp_path)

    allowed_names: list[str] = []
    forbidden_names: list[str] = []
    for index in range(9):
        name = f"team/server-{index:02d}"
        client.create_mcp_server(name=name)
        client.create_mcp_server_version(
            server_json={"name": name, "version": "1.0.0"}, status=MCPStatus.ACTIVE
        )
        client.create_mcp_access_endpoint(
            server_name=name, server_version="1.0.0", url=f"https://example.com/{name}"
        )
        (allowed_names if index % 2 == 0 else forbidden_names).append(name)

    filter_string = _scoped_filter(
        "/api/3.0/mlflow/mcp-servers/endpoints",
        COLLECTION_POLICY_REQUEST_SEARCH_MCP_ACCESS_ENDPOINTS,
        tuple(sorted(allowed_names)),
        "Installed MLflow version cannot express a multi-name MCP endpoint scope.",
    )
    collected = _collect_paginated_names(
        lambda page_token: client.search_mcp_access_endpoints(
            filter_string=filter_string, max_results=2, page_token=page_token
        ),
        lambda endpoint: endpoint.server_name,
    )

    assert sorted(collected) == sorted(allowed_names)
    assert not set(collected) & set(forbidden_names)
