"""Regression coverage for MLflow search-filter grammar and authorization scopes."""

import base64
import json
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mlflow.tracking import MlflowClient
from mlflow.utils import search_utils
from mlflow_kubernetes_plugins.auth import collection_filters
from mlflow_kubernetes_plugins.auth.authorizer import CollectionScope
from mlflow_kubernetes_plugins.auth.core import _get_static_prefix, _RequestIdentity
from mlflow_kubernetes_plugins.auth.request_context import AuthorizationRequest


@pytest.fixture(
    params=[
        ("SEARCH_EXPERIMENTS", "SearchExperimentsUtils", "filter", "name", "experiment_id"),
        ("SEARCH_REGISTERED_MODELS", "SearchModelUtils", "filter", "name", "name"),
        ("SEARCH_MODEL_VERSIONS", "SearchModelVersionUtils", "filter", "name", "name"),
        ("SEARCH_DATASETS", "SearchEvaluationDatasetsUtils", "filter_string", "name", "name"),
        ("SEARCH_MCP_SERVERS", "SearchMCPServerUtils", "filter_string", "name", "name"),
        (
            "SEARCH_MCP_ACCESS_ENDPOINTS",
            "SearchMCPAccessEndpointUtils",
            "filter_string",
            "server_name",
            "server_name",
        ),
    ],
    ids=["experiments", "models", "versions", "datasets", "mcp-servers", "mcp-endpoints"],
)
def search_case(request):
    policy, parser_name, filter_key, scope_key, caller_key = request.param
    return (
        getattr(collection_filters, f"COLLECTION_POLICY_REQUEST_{policy}"),
        getattr(search_utils, parser_name),
        filter_key,
        scope_key,
        caller_key,
    )


def _scope_request(policy, names, query=None, body=None, method="GET"):
    context = AuthorizationRequest(
        authorization_header=None,
        forwarded_access_token=None,
        remote_user_header_value=None,
        remote_groups_header_value=None,
        path="/search",
        method=method,
        workspace="team-a",
        query_params=query or {},
        json_body=body,
    )
    authorizer = Mock()
    authorizer.discover_collection_scope.return_value = CollectionScope(names=names)
    updated, applied = collection_filters.apply_request_collection_filter(
        context,
        policy,
        authorizer=authorizer,
        identity=_RequestIdentity(token="token"),
        workspace_name="team-a",
    )
    if not applied:
        assert updated is context
    return updated, applied


def test_caller_in_filter_is_intersected_with_named_scope(search_case):
    policy, parser, filter_key, scope_key, caller_key = search_case
    caller_filter = f"{caller_key} IN ('1', '2')"
    updated, applied = _scope_request(
        policy, ("allowed",), {filter_key: caller_filter, "page_token": "next"}
    )
    assert applied
    parsed = parser.parse_search_filter(updated.query_params[filter_key])
    assert parsed[:-1] == parser.parse_search_filter(caller_filter)
    assert parsed[-1] == {
        "type": "attribute",
        "key": scope_key,
        "comparator": "=",
        "value": "allowed",
    }
    assert updated.query_params["page_token"] == "next"


@pytest.mark.parametrize(
    "suffix",
    [
        " OR name = 'forbidden'",
        ";",
        "; name = 'forbidden'",
        " -- hide authorization constraint",
        " /* comment */",
        " IN ('broken')",
    ],
)
def test_invalid_caller_filter_fails_closed(search_case, suffix):
    policy, _, filter_key, _, caller_key = search_case
    _, applied = _scope_request(
        policy, ("allowed",), {filter_key: f"{caller_key} = 'allowed'{suffix}"}
    )
    assert not applied


def test_constructed_scope_must_match_authorized_name(search_case, monkeypatch):
    policy, parser, _, scope_key, _ = search_case
    monkeypatch.setattr(
        parser,
        "parse_search_filter",
        lambda _: [{"type": "attribute", "key": scope_key, "comparator": "=", "value": "other"}],
    )
    _, applied = _scope_request(policy, ("allowed",))
    assert not applied


@pytest.mark.parametrize("kind", ["experiments", "models", "versions", "datasets"])
def test_caller_in_filter_scopes_real_storage(tmp_path, kind):
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    if kind == "experiments":
        allowed = client.create_experiment("allowed")
        forbidden = client.create_experiment("forbidden")
        caller_filter = f"experiment_id IN ('{allowed}', '{forbidden}')"
        policy = collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS
        search = client.search_experiments
        filter_key = "filter"
    elif kind == "datasets":
        client.create_dataset(name="allowed")
        client.create_dataset(name="forbidden")
        caller_filter = "name IN ('allowed', 'forbidden')"
        policy = collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_DATASETS
        search = client.search_datasets
        filter_key = "filter_string"
    else:
        for name in ("allowed", "forbidden"):
            client.create_registered_model(name)
            if kind == "versions":
                client.create_model_version(name, source=str(tmp_path / "model"))
        caller_filter = "name IN ('allowed', 'forbidden')"
        policy = (
            collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_MODEL_VERSIONS
            if kind == "versions"
            else collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_REGISTERED_MODELS
        )
        search = (
            client.search_model_versions if kind == "versions" else client.search_registered_models
        )
        filter_key = "filter"
    assert {row.name for row in search(filter_string=caller_filter)} == {"allowed", "forbidden"}
    updated, applied = _scope_request(policy, ("allowed",), {filter_key: caller_filter})
    assert applied
    assert [row.name for row in search(filter_string=updated.query_params[filter_key])] == [
        "allowed"
    ]


@pytest.mark.parametrize(
    "policy,filter_key,caller_key",
    [
        (
            collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS,
            "filter",
            "experiment_id",
        ),
        (collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_DATASETS, "filter_string", "name"),
    ],
)
def test_post_search_intersects_body_and_query_in_filters(policy, filter_key, caller_key):
    updated, applied = _scope_request(
        policy,
        ("allowed",),
        {filter_key: f"{caller_key} IN ('1', '2')"},
        {filter_key: f"{caller_key} IN ('2', '3')", "page_token": "next"},
        method="POST",
    )
    assert applied
    assert updated.json_body[filter_key] == (
        f"{caller_key} IN ('2', '3') AND {caller_key} IN ('1', '2') AND name = 'allowed'"
    )
    assert updated.json_body["page_token"] == "next"


@pytest.mark.parametrize(
    "name", [r"back\slash", r"new\name", "single'quote", 'double"quote', "trailing\\"]
)
@pytest.mark.parametrize("multiple", [False, True], ids=["single-name", "multiple-names"])
def test_scope_literals_round_trip_through_real_parser(search_case, name, multiple, monkeypatch):
    policy, parser, filter_key, scope_key, _ = search_case
    names = (name, "other") if multiple else (name,)
    if policy == collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS and multiple:
        monkeypatch.setattr(
            collection_filters, "resolve_experiment_ids_from_names", lambda _: ("1", "2")
        )
        scope_key = "experiment_id"
        expected = ("1", "2")
    else:
        expected = names if multiple else name
    updated, applied = _scope_request(policy, names)
    assert applied
    assert parser.parse_search_filter(updated.query_params[filter_key]) == [
        {
            "type": "attribute",
            "key": scope_key,
            "comparator": "IN" if multiple else "=",
            "value": expected,
        }
    ]


@pytest.mark.parametrize("name", ["both'and\"quotes", 'x\' OR name = "forbidden" --'])
def test_unrepresentable_scope_name_fails_closed(search_case, name):
    policy, _, _, _, _ = search_case
    _, applied = _scope_request(policy, (name,))
    assert not applied


@pytest.mark.parametrize("kind", ["experiments", "models", "versions", "datasets"])
@pytest.mark.parametrize("name", [r"back\slash", "single'quote", 'double"quote'])
def test_scope_literals_return_exact_name_from_real_storage(tmp_path, kind, name):
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    if kind == "experiments":
        for value in (name, "forbidden"):
            client.create_experiment(value)
        policy = collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_EXPERIMENTS
        search = client.search_experiments
        filter_key = "filter"
    elif kind == "datasets":
        for value in (name, "forbidden"):
            client.create_dataset(name=value)
        policy = collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_DATASETS
        search = client.search_datasets
        filter_key = "filter_string"
    else:
        for value in (name, "forbidden"):
            client.create_registered_model(value)
            if kind == "versions":
                client.create_model_version(value, source=str(tmp_path / "model"))
        policy = (
            collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_MODEL_VERSIONS
            if kind == "versions"
            else collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_REGISTERED_MODELS
        )
        search = (
            client.search_model_versions if kind == "versions" else client.search_registered_models
        )
        filter_key = "filter"
    updated, applied = _scope_request(policy, (name,))
    assert applied
    assert [row.name for row in search(filter_string=updated.query_params[filter_key])] == [name]


@pytest.mark.parametrize("filter_key", ["filter_string", "filterString"])
@pytest.mark.parametrize("names", [("allowed",), ("allowed", "other")])
def test_dataset_post_alias_normalization_preserves_body_and_query(filter_key, names):
    body = {filter_key: "name = 'allowed'", "page_token": "next"}
    original = dict(body)
    updated, applied = _scope_request(
        collection_filters.COLLECTION_POLICY_REQUEST_SEARCH_DATASETS,
        names,
        {"filter_string": "name IN ('allowed', 'forbidden')"},
        body,
        method="POST",
    )
    assert applied
    assert body == original
    assert updated.json_body["page_token"] == "next"
    assert "filterString" not in updated.json_body
    parsed = search_utils.SearchEvaluationDatasetsUtils.parse_search_filter(
        updated.json_body["filter_string"]
    )
    assert parsed[:-1] == search_utils.SearchEvaluationDatasetsUtils.parse_search_filter(
        "name = 'allowed' AND name IN ('allowed', 'forbidden')"
    )


@pytest.fixture(scope="module")
def dataset_search_http(tmp_path_factory):
    from fastapi.testclient import TestClient
    from mlflow_kubernetes_plugins.auth import middleware
    from mlflow_kubernetes_plugins.auth.authorizer import AuthorizationMode, KubernetesAuthConfig
    from mlflow_kubernetes_plugins.auth.compiler import _reset_compiled_rules

    root = tmp_path_factory.mktemp("dataset-post-alias")
    client = MlflowClient(tracking_uri=f"sqlite:///{root}/tracking.db")
    for name in ("allowed-a", "allowed-b", "forbidden"):
        client.create_dataset(name=name)
    store = client._tracking_client.store
    calls = []
    original_search = store.search_datasets

    def search(*args, **kwargs):
        calls.append((args, kwargs))
        return original_search(*args, **kwargs)

    authorizer = Mock()
    authorizer.is_allowed.side_effect = lambda identity, *args, **kwargs: (
        identity.user == "broad-user" or kwargs.get("resource_name") in ("allowed-a", "allowed-b")
    )
    authorizer.discover_collection_scope.return_value = CollectionScope(
        names=("allowed-a", "allowed-b")
    )
    cfg = KubernetesAuthConfig(
        authorization_mode=AuthorizationMode.SUBJECT_ACCESS_REVIEW,
        workspaces_enabled=False,
        namespace="team-a",
    )
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setenv("MLFLOW_ENABLE_WORKSPACES", "false")
        patcher.setenv("MLFLOW_SERVER_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")
        patcher.setattr(middleware.KubernetesAuthConfig, "from_env", lambda: cfg)
        patcher.setattr(middleware, "KubernetesAuthorizer", lambda config_values: authorizer)
        patcher.setattr("mlflow.server.handlers._get_tracking_store", lambda: store)
        patcher.setattr(store, "search_datasets", search)
        _reset_compiled_rules()
        try:
            with TestClient(middleware.create_app()) as http:
                yield http, calls, _get_static_prefix() or ""
        finally:
            _reset_compiled_rules()


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("filter_key", ["filter_string", "filterString"])
@pytest.mark.parametrize("user", ["alice", "broad-user"])
def test_dataset_post_filter_alias_reaches_real_storage(
    dataset_search_http, prefix, filter_key, user
):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.post(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        json={filter_key: "name IN ('allowed-a', 'forbidden')", "max_results": 100},
        headers={"x-remote-user": user},
    )
    assert response.status_code == 200, response.text
    expected = ["allowed-a", "forbidden"] if user == "broad-user" else ["allowed-a"]
    assert sorted(row["name"] for row in response.json().get("datasets", [])) == expected
    assert len(calls) == 1


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("user", ["alice", "broad-user"])
@pytest.mark.parametrize("camel_filter", ["name = 'allowed-a'", "name = 'forbidden'"])
def test_dataset_post_duplicate_aliases_never_query_storage(
    dataset_search_http, prefix, user, camel_filter
):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.post(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        json={"filter_string": "name = 'allowed-a'", "filterString": camel_filter},
        headers={"x-remote-user": user},
    )
    assert response.status_code == (400 if user == "broad-user" else 403), response.text
    assert calls == []


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("filter_key", ["filter_string", "filterString"])
@pytest.mark.parametrize("user", ["alice", "broad-user"])
def test_dataset_post_filter_alias_intersects_query_for_named_access(
    dataset_search_http, prefix, filter_key, user
):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.post(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        params={"filter_string": "name = 'allowed-b'"},
        json={filter_key: "name = 'allowed-a'"},
        headers={"x-remote-user": user},
    )
    assert response.status_code == 200, response.text
    # Broad requests retain MLflow's POST-body precedence; named scoping
    # intersects both sources so neither can widen the authorized request.
    expected = ["allowed-a"] if user == "broad-user" else []
    assert [row["name"] for row in response.json().get("datasets", [])] == expected
    assert len(calls) == 1


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("filter_key", ["filter_string", "filterString"])
def test_dataset_post_alias_cannot_hide_authorization_with_or(
    dataset_search_http, prefix, filter_key
):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.post(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        json={filter_key: "name = 'allowed-a' OR name = 'forbidden'"},
        headers={"x-remote-user": "alice"},
    )
    assert response.status_code == 403, response.text
    assert calls == []


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
def test_dataset_get_filter_still_reaches_real_storage(dataset_search_http, prefix):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.get(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        params={"filter_string": "name = 'allowed-a'"},
        headers={"x-remote-user": "alice"},
    )
    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json().get("datasets", [])] == ["allowed-a"]
    assert len(calls) == 1


@pytest.fixture(scope="module")
def collection_search_http(dataset_search_http):
    from mlflow.entities import Span
    from mlflow.server.handlers import _get_tracking_store
    from mlflow_kubernetes_plugins.auth import resource_names

    http, _, static_prefix = dataset_search_http
    store = _get_tracking_store()
    client = MlflowClient(tracking_uri=store.db_uri, registry_uri=store.db_uri)
    experiments = {}
    traces = {}
    for name in ("allowed-a", "allowed-b", "forbidden"):
        experiments[name] = client.create_experiment(name)
        client.create_run(experiments[name])
        client.create_registered_model(name)
        client.create_model_version(name, source="model")
        store.register_scorer(experiments[name], "test-scorer", '{"name":"test-scorer"}')
        trace_id = "tr-" + uuid.uuid4().hex
        traces[name] = trace_id
        span = Span.from_dict(
            {
                "trace_id": base64.b64encode(bytes.fromhex(trace_id[3:])).decode(),
                "span_id": base64.b64encode(uuid.uuid4().bytes[:8]).decode(),
                "parent_span_id": None,
                "name": "span-" + name,
                "start_time_unix_nano": 1700000000000000000,
                "end_time_unix_nano": 1700000000001000000,
                "status": {"code": "STATUS_CODE_OK"},
                "attributes": {
                    "mlflow.traceRequestId": json.dumps(trace_id),
                    "mlflow.spanType": json.dumps("CHAIN"),
                },
            }
        )
        store.log_spans(experiments[name], [span])
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(resource_names, "_get_tracking_store", lambda: store)
        patcher.setattr(
            "mlflow.server.handlers._get_model_registry_store",
            lambda: client._get_registry_client().store,
        )
        resource_names._experiment_name_cache.clear()
        try:
            yield SimpleNamespace(
                http=http, static_prefix=static_prefix, experiments=experiments, traces=traces
            )
        finally:
            resource_names._experiment_name_cache.clear()


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("user", ["alice", "broad-user"])
@pytest.mark.parametrize("kind", ["experiments", "models", "versions", "datasets", "traces"])
def test_collection_get_json_body_preserves_caller_input(
    collection_search_http, prefix, user, kind
):
    server = collection_search_http
    routes = {
        "experiments": ("/2.0/mlflow/experiments/search", "experiments"),
        "models": ("/2.0/mlflow/registered-models/search", "registered_models"),
        "versions": ("/2.0/mlflow/model-versions/search", "model_versions"),
        "datasets": ("/3.0/mlflow/datasets/search", "datasets"),
        "traces": ("/2.0/mlflow/traces", "traces"),
    }
    path, key = routes[kind]
    if kind == "traces":
        body = {"experiment_ids": [server.experiments["allowed-a"]], "maxResults": 1}
    else:
        filter_key = "filterString" if kind == "datasets" else "filter"
        body = {filter_key: "name = 'allowed-a'", "maxResults": 1}
        if kind == "experiments":
            body["viewType"] = "ACTIVE_ONLY"
    response = server.http.request(
        "GET",
        server.static_prefix + prefix + path,
        json=body,
        headers={"x-remote-user": user},
    )
    assert response.status_code == 200, response.text
    rows = response.json().get(key, [])
    if kind == "traces":
        assert [row["request_id"] for row in rows] == [server.traces["allowed-a"]]
    else:
        assert [row["name"] for row in rows] == ["allowed-a"]


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("user", ["alice", "broad-user"])
@pytest.mark.parametrize("kind", ["experiments", "datasets"])
def test_collection_legacy_json_string_post_preserves_caller_input(
    collection_search_http, prefix, user, kind
):
    server = collection_search_http
    if kind == "experiments":
        path, key = "/2.0/mlflow/experiments/search", "experiments"
        body = {"filter": "name = 'allowed-a'", "max_results": 1}
    else:
        path, key = "/3.0/mlflow/datasets/search", "datasets"
        body = {"filterString": "name = 'allowed-a'", "maxResults": 1}
    response = server.http.post(
        server.static_prefix + prefix + path,
        json=json.dumps(body),
        headers={"x-remote-user": user},
    )
    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json().get(key, [])] == ["allowed-a"]


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("kind", ["experiments", "models", "versions", "datasets"])
def test_collection_get_body_preserves_aliases_order_and_page_token(
    collection_search_http, prefix, kind
):
    server = collection_search_http
    routes = {
        "experiments": ("/2.0/mlflow/experiments/search", "experiments"),
        "models": ("/2.0/mlflow/registered-models/search", "registered_models"),
        "versions": ("/2.0/mlflow/model-versions/search", "model_versions"),
        "datasets": ("/3.0/mlflow/datasets/search", "datasets"),
    }
    path, key = routes[kind]
    filter_key = "filterString" if kind == "datasets" else "filter"
    body = {
        filter_key: "name IN ('allowed-a', 'allowed-b', 'forbidden')",
        "maxResults": 1,
        "orderBy": ["name DESC"],
    }
    if kind == "experiments":
        body["filter"] = (
            "experiment_id IN ("
            + ", ".join(repr(value) for value in server.experiments.values())
            + ")"
        )
    collected = []
    for _ in range(4):
        response = server.http.request(
            "GET",
            server.static_prefix + prefix + path,
            json=body,
            headers={"x-remote-user": "alice"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        rows = payload.get(key, [])
        assert len(rows) <= 1
        collected.extend(row["name"] for row in rows)
        if not (page_token := payload.get("next_page_token")):
            break
        body["pageToken"] = page_token
    assert not page_token
    assert collected == ["allowed-b", "allowed-a"]


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("camel_case", [False, True])
@pytest.mark.parametrize("user", ["alice", "broad-user"])
def test_batch_trace_get_body_enforces_scope_before_loading_spans(
    collection_search_http, prefix, camel_case, user
):
    server = collection_search_http
    body = {
        "trace_ids": [server.traces[name] for name in ("allowed-a", "forbidden")],
        "experimentIds" if camel_case else "experiment_ids": [
            server.experiments[name] for name in ("allowed-a", "forbidden")
        ],
    }
    response = server.http.request(
        "GET",
        server.static_prefix + prefix + "/3.0/mlflow/traces/batchGet",
        json=body,
        headers={"x-remote-user": user},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["traces"]) == (2 if user == "broad-user" else 1)
    assert "span-allowed-a" in response.text
    if user == "alice":
        assert "span-forbidden" not in response.text
        assert server.traces["forbidden"] not in response.text


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize(
    "selector", [None, "experiment_id", "experimentId", "experiment_ids", "experimentIds"]
)
def test_scorer_get_json_body_preserves_selectors(collection_search_http, prefix, selector):
    server = collection_search_http
    if selector is None:
        body = {}
        expected = ("allowed-a", "allowed-b")
    elif selector in ("experiment_id", "experimentId"):
        body = {selector: server.experiments["allowed-a"]}
        expected = ("allowed-a",)
    else:
        body = {selector: [server.experiments[name] for name in ("allowed-a", "forbidden")]}
        expected = ("allowed-a",)
    response = server.http.request(
        "GET",
        server.static_prefix + prefix + "/3.0/mlflow/scorers/list",
        json=body,
        headers={"x-remote-user": "alice"},
    )
    assert response.status_code == 200, response.text
    assert sorted(str(row["experiment_id"]) for row in response.json()["scorers"]) == sorted(
        server.experiments[name] for name in expected
    )


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("body", ["{bad", "[]", "42", '"still-encoded"'])
def test_invalid_legacy_post_body_never_reaches_storage(dataset_search_http, prefix, body):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.post(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        json=body,
        headers={"x-remote-user": "alice"},
    )
    assert response.status_code == 403, response.text
    assert calls == []


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("body", ["", "null", '"null"', "{}"])
@pytest.mark.parametrize("user", ["alice", "broad-user"])
def test_empty_dataset_post_body_preserves_authorized_scope(
    dataset_search_http, prefix, body, user
):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.post(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        content=body,
        headers={"x-remote-user": user, "content-type": "application/json"},
    )
    assert response.status_code == 200, response.text
    expected = ["allowed-a", "allowed-b"]
    if user == "broad-user":
        expected.append("forbidden")
    assert sorted(row["name"] for row in response.json().get("datasets", [])) == expected
    assert len(calls) == 1


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
@pytest.mark.parametrize("body", [b"{bad", b" ", b"\xff", b"[]", b"42", b"false"])
def test_invalid_dataset_post_body_never_reaches_storage(dataset_search_http, prefix, body):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.post(
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        content=body,
        headers={"x-remote-user": "alice", "content-type": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert calls == []


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
def test_get_query_precedence_ignores_json_body(dataset_search_http, prefix):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.request(
        "GET",
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        params={"filter_string": "name = 'allowed-a'"},
        json={"filterString": "name = 'forbidden'"},
        headers={"x-remote-user": "alice"},
    )
    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json()["datasets"]] == ["allowed-a"]
    assert len(calls) == 1


@pytest.mark.parametrize("prefix", ["/api", "/ajax-api"])
def test_get_body_duplicate_aliases_never_reach_storage(dataset_search_http, prefix):
    http, calls, static_prefix = dataset_search_http
    calls.clear()
    response = http.request(
        "GET",
        static_prefix + prefix + "/3.0/mlflow/datasets/search",
        json={"filterString": "name = 'forbidden'", "filter_string": "name = 'allowed-a'"},
        headers={"x-remote-user": "alice"},
    )
    assert response.status_code == 403, response.text
    assert calls == []
