from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kubernetes.client.exceptions import ApiException
from mlflow.exceptions import MlflowException
from mlflow_kubernetes_plugins.workspace_plugin import caches
from mlflow_kubernetes_plugins.workspace_plugin.caches import NamespaceCache
from urllib3.exceptions import ReadTimeoutError


def namespace(name, *, version="1", description=None):
    annotations = {caches.DEFAULT_DESCRIPTION_ANNOTATION: description} if description else {}
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, annotations=annotations, resource_version=version)
    )


def listing(*namespaces, version="1"):
    return SimpleNamespace(
        items=list(namespaces), metadata=SimpleNamespace(resource_version=version)
    )


@pytest.fixture
def make_cache(monkeypatch):
    # Drive watch iterations synchronously; tests must not depend on scheduling
    # or create threads that survive the test.
    monkeypatch.setattr(caches.threading.Thread, "start", lambda self: None)

    def create(*namespaces, selector=None, exclusions=()):
        api = MagicMock()
        api.list_namespace.return_value = listing(*namespaces)
        cache = NamespaceCache(api, selector, exclusions)
        api.list_namespace.reset_mock()
        return cache, api

    return create


def test_cache_hit_does_not_call_kubernetes(make_cache):
    cache, api = make_cache(namespace("existing", description="Existing workspace"))

    assert cache.get_namespace("existing").description == "Existing workspace"
    api.list_namespace.assert_not_called()


def test_independent_stale_workers_resolve_new_namespace(make_cache):
    for _ in range(2):
        cache, api = make_cache(namespace("old"))
        api.list_namespace.return_value = listing(
            namespace("new", description="New workspace"), version="12"
        )

        info = cache.get_namespace("new")

        assert info.name == "new"
        assert info.description == "New workspace"
        api.list_namespace.assert_called_once_with(
            field_selector="metadata.name=new",
            label_selector=None,
            watch=False,
            _request_timeout=(5, 30),
        )
        # A targeted lookup cannot advance the collection watch cursor.
        assert cache._resource_version == "1"


def test_missing_namespace_is_not_negatively_cached(make_cache):
    cache, api = make_cache()
    api.list_namespace.side_effect = [listing(), listing(namespace("new"))]

    assert cache.get_namespace("new") is None
    assert cache.get_namespace("new").name == "new"
    assert api.list_namespace.call_count == 2


@pytest.mark.parametrize("selector", ["team=mlflow", "team in (mlflow,analytics),!disabled"])
def test_lookup_preserves_kubernetes_label_selector(make_cache, selector):
    cache, api = make_cache(selector=selector)
    # Kubernetes evaluates the selector and returns no namespace if it doesn't
    # match. No client-side selector parser or unfiltered GET may bypass it.
    api.list_namespace.return_value = listing()

    assert cache.get_namespace("hidden") is None
    assert api.list_namespace.call_args.kwargs["label_selector"] == selector
    api.read_namespace.assert_not_called()


def test_excluded_namespace_is_not_looked_up(make_cache):
    cache, api = make_cache(exclusions=("kube-*", "secret-*"))

    assert cache.get_namespace("kube-system") is None
    assert cache.get_namespace("secret-team") is None
    api.list_namespace.assert_not_called()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "UNAUTHENTICATED"),
        (403, "PERMISSION_DENIED"),
        (500, "INTERNAL_ERROR"),
        (404, "INTERNAL_ERROR"),
    ],
)
def test_api_failure_is_not_reported_as_missing(make_cache, status, code):
    cache, api = make_cache()
    api.list_namespace.side_effect = ApiException(status=status, reason="sensitive server details")

    with pytest.raises(MlflowException, match="Failed to verify Kubernetes namespace") as exc:
        cache.get_namespace("new")

    assert exc.value.error_code == code
    assert f"HTTP {status}" in exc.value.message
    assert "sensitive server details" not in exc.value.message


def test_live_lookup_timeout_is_not_reported_as_missing(make_cache):
    cache, api = make_cache()
    api.list_namespace.side_effect = ReadTimeoutError(None, None, "read timed out")

    with pytest.raises(MlflowException, match="Check Kubernetes API connectivity") as exc:
        cache.get_namespace("new")

    assert exc.value.error_code == "INTERNAL_ERROR"


def test_lookup_does_not_overwrite_concurrent_watch_event(make_cache):
    cache, api = make_cache()

    def lookup(**kwargs):
        cache._handle_event(
            {"type": "ADDED", "object": namespace("new", version="13", description="Latest")}
        )
        return listing(namespace("new", description="Earlier"), version="12")

    api.list_namespace.side_effect = lookup
    assert cache.get_namespace("new").description == "Earlier"
    assert cache.get_namespace("new").description == "Latest"
    assert cache._resource_version == "13"


@pytest.mark.parametrize("failure", [None, "expired", "timeout", "api", "error_event"])
def test_watch_reconnect_relists_and_repairs_cache(make_cache, monkeypatch, failure):
    cache, api = make_cache(namespace("deleted"))
    api.list_namespace.return_value = listing(namespace("new"), version="12")
    monkeypatch.setattr(cache._stop_event, "wait", lambda timeout: False)
    first_watch = MagicMock()
    if failure == "expired":
        first_watch.stream.side_effect = ApiException(status=410)
    elif failure == "timeout":
        first_watch.stream.side_effect = ReadTimeoutError(None, None, "read timed out")
    elif failure == "api":
        first_watch.stream.side_effect = ApiException(status=503)
    elif failure == "error_event":
        first_watch.stream.return_value = iter(
            [
                {"type": "ERROR", "object": {"code": 410}},
                # Must stop consuming this obsolete stream on ERROR.
                {"type": "ADDED", "object": namespace("obsolete")},
            ]
        )
    else:
        first_watch.stream.return_value = iter(())

    second_watch = MagicMock()

    def recovered_stream(*args, **kwargs):
        assert [info.name for info in cache.list_namespaces()] == ["new"]
        assert cache._resource_version == "12"
        cache.stop()
        return iter(())

    second_watch.stream.side_effect = recovered_stream
    watches = MagicMock(side_effect=[first_watch, second_watch])
    monkeypatch.setattr(caches.watch, "Watch", watches)

    cache._run()

    assert watches.call_count == 2
    api.list_namespace.assert_called_once_with(
        label_selector=None, watch=False, _request_timeout=(5, 30)
    )
    first_watch.stream.assert_called_once_with(
        api.list_namespace,
        label_selector=None,
        resource_version="1",
        timeout_seconds=300,
        _request_timeout=(5, 330),
    )
    assert second_watch.stream.call_args.kwargs["resource_version"] == "12"
    first_watch.stop.assert_called_once()
    second_watch.stop.assert_called_once()


def test_watch_retries_failed_relist(make_cache, monkeypatch):
    cache, api = make_cache()
    cache._resource_version = None
    api.list_namespace.side_effect = [
        ReadTimeoutError(None, None, "read timed out"),
        ApiException(status=503),
        listing(namespace("new"), version="12"),
    ]
    monkeypatch.setattr(cache._stop_event, "wait", lambda timeout: False)
    watcher = MagicMock()

    def stop_after_recovery(*args, **kwargs):
        assert cache.get_namespace("new").name == "new"
        cache.stop()
        return iter(())

    watcher.stream.side_effect = stop_after_recovery
    monkeypatch.setattr(caches.watch, "Watch", lambda: watcher)

    cache._run()

    assert api.list_namespace.call_count == 3
    assert watcher.stream.call_args.kwargs["resource_version"] == "12"


@pytest.mark.parametrize(
    "obj",
    [
        {"metadata": {"resourceVersion": "12"}},
        SimpleNamespace(metadata=SimpleNamespace(resource_version="12")),
    ],
)
def test_bookmark_without_name_advances_cursor(make_cache, obj):
    cache, _ = make_cache()
    cache._handle_event({"type": "BOOKMARK", "object": obj})
    assert cache._resource_version == "12"


def test_error_event_without_name_invalidates_cursor(make_cache):
    cache, _ = make_cache()
    cache._handle_event({"type": "ERROR", "object": {"code": 410}})
    assert cache._resource_version is None
