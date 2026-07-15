"""FastAPI middleware wiring for the Kubernetes auth plugin."""

from __future__ import annotations

import atexit
import copy
import importlib
import json
import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, cast
from urllib.parse import urlencode

from fastapi import Request
from mlflow.exceptions import MlflowException
from mlflow.protos import databricks_pb2
from mlflow.server import app as mlflow_app
from mlflow.server import handlers as mlflow_handlers
from mlflow.server.fastapi_app import create_fastapi_app
from mlflow.server.workspace_helpers import WORKSPACE_HEADER_NAME, resolve_workspace_from_header
from mlflow.utils import workspace_context
from mlflow.utils.search_utils import SearchUtils
from starlette.concurrency import iterate_in_threadpool
from starlette.datastructures import QueryParams
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import Scope

import mlflow_kubernetes_plugins.auth.core as core_mod
from mlflow_kubernetes_plugins.auth.authorizer import KubernetesAuthConfig, KubernetesAuthorizer
from mlflow_kubernetes_plugins.auth.collection_filters import (
    apply_response_collection_filters,
    can_skip_response_collection_filters,
)
from mlflow_kubernetes_plugins.auth.compiler import (
    _compile_authorization_rules,
    _extract_path_params,
    _validate_fastapi_route_authorization,
)
from mlflow_kubernetes_plugins.auth.constants import RESOURCE_MCP_SERVERS
from mlflow_kubernetes_plugins.auth.core import (
    _AUTHORIZATION_HANDLED,
    _authorize_request_async,
    _canonicalize_path,
    _is_unprotected_path,
    _RequestIdentity,
)
from mlflow_kubernetes_plugins.auth.graphql import (
    get_graphql_authorization_middleware as _get_graphql_authorization_middleware,
)
from mlflow_kubernetes_plugins.auth.graphql import (
    validate_graphql_field_authorization as _validate_graphql_field_authorization,
)
from mlflow_kubernetes_plugins.auth.request_context import (
    AuthorizationRequest,
    build_fastapi_authorization_request,
)
from mlflow_kubernetes_plugins.auth.resource_names import apply_response_cache_updates

if TYPE_CHECKING:
    from flask import Flask

_REQUEST_RAW_BODY_STATE_KEY = "mlflow_k8s_raw_body"
_REQUEST_JSON_BODY_STATE_KEY = "mlflow_k8s_json_body"
_REQUEST_BODY_LOADED_STATE_KEY = "mlflow_k8s_body_loaded"
_GRAPHQL_AUTHORIZER: ContextVar[KubernetesAuthorizer | None] = ContextVar(
    "mlflow_k8s_graphql_authorizer",
    default=None,
)


def _replace_scope_headers(scope: Scope, updates: dict[str, str]) -> None:
    """Replace (or add) ASGI scope headers, matching case-insensitively."""
    encoded = {k.lower().encode("latin-1"): v.encode("latin-1") for k, v in updates.items()}
    headers = [
        (header_name, header_value)
        for header_name, header_value in scope.get("headers", [])
        if header_name.lower() not in encoded
    ]
    headers.extend(encoded.items())
    scope["headers"] = headers


def _request_query_values(request_context: AuthorizationRequest, key: str) -> list[str]:
    value = request_context.query_params.get(key)
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _request_query_value(request_context: AuthorizationRequest, key: str) -> str | None:
    values = _request_query_values(request_context, key)
    return values[0] if values else None


def _backfill_readable_mcp_results(
    *,
    can_read: Callable[[str], bool],
    readable: list[dict[str, object]],
    max_results: int,
    next_token: str | None,
    fetch_page: Callable[[str | None], Any],
    get_name: Callable[[Any], str],
    to_dict: Callable[[Any], dict[str, object]],
) -> str | None:
    while len(readable) < max_results and next_token:
        start_offset = SearchUtils.parse_start_offset_from_page_token(next_token)
        page = fetch_page(next_token)
        if not page:
            return None
        consumed = 0
        for item in page:
            if len(readable) >= max_results:
                break
            consumed += 1
            if can_read(get_name(item)):
                readable.append(to_dict(item))
        if consumed < len(page):
            next_token = SearchUtils.create_page_token(start_offset + consumed)
        else:
            next_token = page.token
        if isinstance(next_token, bytes):
            next_token = next_token.decode("utf-8")
    return next_token


def _mcp_search_response_dict(response_class_name: str, item: Any) -> dict[str, object]:
    mcp_server_api = importlib.import_module("mlflow.server.mcp_server_api")
    response_class = getattr(mcp_server_api, response_class_name)
    return response_class.from_entity(item).model_dump(mode="json")


def _mcp_server_read_predicate(
    authorizer: KubernetesAuthorizer,
    identity: _RequestIdentity,
    workspace_name: str,
) -> Callable[[str], bool]:
    return lambda resource_name: authorizer.is_allowed(
        identity,
        RESOURCE_MCP_SERVERS,
        "get",
        workspace_name,
        resource_name=resource_name,
    )


def _mcp_search_store() -> Any:
    return cast(Any, mlflow_handlers._get_tracking_store())


def _filter_search_mcp_servers(
    payload: dict[str, object],
    *,
    request_context: AuthorizationRequest,
    authorizer: KubernetesAuthorizer,
    identity: _RequestIdentity,
    workspace_name: str,
) -> dict[str, object]:
    data = dict(payload)
    mcp_servers = data.get("mcp_servers")
    if not isinstance(mcp_servers, list):
        return data

    can_read = _mcp_server_read_predicate(authorizer, identity, workspace_name)
    # Filter out unreadable servers from the already returned page.
    readable: list[dict[str, object]] = []
    for server in mcp_servers:
        if not isinstance(server, dict):
            continue
        server_name = server.get("name")
        if isinstance(server_name, str) and can_read(server_name):
            readable.append(cast(dict[str, object], server))

    max_results = int(_request_query_value(request_context, "max_results") or "100")
    filter_string = _request_query_value(request_context, "filter_string")
    order_by = _request_query_values(request_context, "order_by") or None

    # Re-fetch to fill max results after response filtering.
    data["next_page_token"] = _backfill_readable_mcp_results(
        can_read=can_read,
        readable=readable,
        max_results=max_results,
        next_token=_normalize_page_token(data.get("next_page_token")),
        fetch_page=lambda token: _mcp_search_store().search_mcp_servers(
            filter_string=filter_string,
            max_results=max_results,
            order_by=order_by,
            page_token=token,
        ),
        get_name=lambda server: server.name,
        to_dict=lambda server: _mcp_search_response_dict("MCPServerResponse", server),
    )
    data["mcp_servers"] = readable[:max_results]
    return data


def _filter_search_mcp_endpoints(
    payload: dict[str, object],
    *,
    request_context: AuthorizationRequest,
    authorizer: KubernetesAuthorizer,
    identity: _RequestIdentity,
    workspace_name: str,
) -> dict[str, object]:
    data = dict(payload)
    endpoints = data.get("mcp_access_endpoints")
    if not isinstance(endpoints, list):
        return data

    can_read = _mcp_server_read_predicate(authorizer, identity, workspace_name)
    # Filter out unreadable endpoints from the already returned page.
    readable: list[dict[str, object]] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        server_name = endpoint.get("server_name")
        if isinstance(server_name, str) and can_read(server_name):
            readable.append(cast(dict[str, object], endpoint))

    max_results = int(_request_query_value(request_context, "max_results") or "100")
    filter_string = _request_query_value(request_context, "filter_string")
    order_by = _request_query_values(request_context, "order_by") or None
    server_version = _request_query_value(request_context, "server_version")
    server_alias = _request_query_value(request_context, "server_alias")

    # Re-fetch to fill max results after response filtering.
    data["next_page_token"] = _backfill_readable_mcp_results(
        can_read=can_read,
        readable=readable,
        max_results=max_results,
        next_token=_normalize_page_token(data.get("next_page_token")),
        fetch_page=lambda token: _mcp_search_store().search_mcp_access_endpoints(
            filter_string=filter_string,
            max_results=max_results,
            order_by=order_by,
            page_token=token,
            server_version=server_version,
            server_alias=server_alias,
        ),
        get_name=lambda endpoint: endpoint.server_name,
        to_dict=lambda endpoint: _mcp_search_response_dict("MCPAccessEndpointResponse", endpoint),
    )
    data["mcp_access_endpoints"] = readable[:max_results]
    return data


def _backfill_mcp_search_response(
    payload: dict[str, object],
    *,
    request_context: AuthorizationRequest,
    authorizer: KubernetesAuthorizer,
    identity: _RequestIdentity,
    workspace_name: str,
) -> dict[str, object]:
    path = request_context.path
    if path in (
        "/ajax-api/3.0/mlflow/mcp-servers",
        "/api/3.0/mlflow/mcp-servers",
    ):
        return _filter_search_mcp_servers(
            payload,
            request_context=request_context,
            authorizer=authorizer,
            identity=identity,
            workspace_name=workspace_name,
        )
    if path in (
        "/ajax-api/3.0/mlflow/mcp-servers/endpoints",
        "/api/3.0/mlflow/mcp-servers/endpoints",
    ):
        return _filter_search_mcp_endpoints(
            payload,
            request_context=request_context,
            authorizer=authorizer,
            identity=identity,
            workspace_name=workspace_name,
        )
    return payload


def _normalize_page_token(token: object) -> str | None:
    if isinstance(token, bytes):
        return token.decode("utf-8")
    if isinstance(token, str) and token:
        return token
    return None


class KubernetesAuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for Kubernetes-based authorization."""

    def __init__(self, app, authorizer, config_values):
        super().__init__(app)
        self.authorizer = authorizer
        self.config_values = config_values

    @staticmethod
    def _set_request_json_body(request: Request, payload: dict[str, object]) -> None:
        """Overwrite the ASGI request body with *payload* and update scope state/headers."""
        raw_body = json.dumps(payload).encode("utf-8")
        state = request.scope.setdefault("state", {})
        state[_REQUEST_RAW_BODY_STATE_KEY] = raw_body
        state[_REQUEST_JSON_BODY_STATE_KEY] = payload
        state[_REQUEST_BODY_LOADED_STATE_KEY] = True
        request._body = raw_body
        _replace_scope_headers(
            request.scope,
            {
                "content-length": str(len(raw_body)),
                "content-type": "application/json",
            },
        )

    @staticmethod
    def _set_request_query_params(request: Request, query_params: dict[str, object]) -> None:
        """Re-encode *query_params* into the ASGI scope and Starlette's cached QueryParams."""
        items: list[tuple[str, str]] = []
        for key, value in query_params.items():
            if isinstance(value, list):
                items.extend((key, str(item)) for item in value)
            elif value is not None:
                items.append((key, str(value)))
        query_string = urlencode(items, doseq=True).encode("utf-8")
        request.scope["query_string"] = query_string
        request._query_params = QueryParams(query_string)

    @staticmethod
    def _request_can_have_json_body(request: Request) -> bool:
        return request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and (
            "json" in request.headers.get("content-type", "").lower()
        )

    @classmethod
    async def _ensure_request_json_body(cls, request: Request) -> object | None:
        """Lazily load and cache the JSON body from the ASGI request.

        Returns the parsed payload (or ``None`` when the content-type is not JSON).
        Subsequent calls return the cached value without re-reading the body stream.
        """
        if not cls._request_can_have_json_body(request):
            return None
        state = request.scope.setdefault("state", {})
        if state.get(_REQUEST_BODY_LOADED_STATE_KEY):
            return state.get(_REQUEST_JSON_BODY_STATE_KEY)

        # BaseHTTPMiddleware caches request.body() on the outer Request and replays request._body
        # to the downstream app, so this gives us lazy loading without a second ASGI middleware.
        raw_body = bytes(await request.body())
        state[_REQUEST_RAW_BODY_STATE_KEY] = raw_body
        try:
            payload = json.loads(raw_body) if raw_body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        state[_REQUEST_JSON_BODY_STATE_KEY] = payload
        state[_REQUEST_BODY_LOADED_STATE_KEY] = True
        return payload

    @classmethod
    def _apply_request_context_rewrites(
        cls,
        request: Request,
        *,
        original_request_context,
        updated_request_context,
        username: str | None,
        override_run_user: bool,
    ) -> None:
        """Propagate authorization-side mutations back into the live ASGI request.

        This covers two cases: rewriting the JSON body (e.g. injecting ``user_id``
        for run-ownership override, or applying collection filter changes) and
        updating query parameters that were narrowed during authorization.
        The ASGI request is only mutated when a change is actually detected.
        """
        body_changed = (
            updated_request_context.json_body is not original_request_context.json_body
            and updated_request_context.json_body != original_request_context.json_body
        )
        needs_user_override = override_run_user and username
        if isinstance(updated_request_context.json_body, dict) and (
            body_changed or needs_user_override
        ):
            payload = (
                copy.deepcopy(updated_request_context.json_body)
                if needs_user_override
                else updated_request_context.json_body
            )
            if needs_user_override:
                payload["user_id"] = username
            cls._set_request_json_body(request, payload)

        if updated_request_context.query_params != original_request_context.query_params:
            cls._set_request_query_params(request, updated_request_context.query_params)

    async def _filter_workspace_list_response(self, response, *, auth_result) -> None:
        """Strip workspaces the caller cannot access from a ``{"workspaces": [...]}`` response."""
        payload, _ = await self._read_json_response_payload(response)
        if not isinstance(payload, dict):
            return
        workspaces = payload.get("workspaces")
        if not isinstance(workspaces, list):
            return
        workspace_names = [ws.get("name") for ws in workspaces if isinstance(ws, dict)]
        accessible = self.authorizer.accessible_workspaces(
            auth_result.identity,
            [name for name in workspace_names if isinstance(name, str)],
        )
        filtered_workspaces = [
            ws for ws in workspaces if isinstance(ws, dict) and ws.get("name") in accessible
        ]
        if filtered_workspaces != workspaces:
            updated_payload = dict(payload)
            updated_payload["workspaces"] = filtered_workspaces
            self._replace_json_response_payload(response, updated_payload)

    async def _apply_collection_response_filters(
        self,
        response,
        *,
        auth_result,
        response_workspace_name: str | None,
    ) -> None:
        if not auth_result.response_filter_required:
            return
        if not response_workspace_name or response.status_code >= 400:
            return
        if can_skip_response_collection_filters(
            auth_result.rules,
            authorizer=self.authorizer,
            identity=auth_result.identity,
            workspace_name=response_workspace_name,
        ):
            return
        payload, _ = await self._read_json_response_payload(response)
        if not isinstance(payload, dict):
            self._replace_json_response_payload(response, {})
            return
        filtered_payload, enforceable = apply_response_collection_filters(
            payload,
            auth_result.rules,
            authorizer=self.authorizer,
            identity=auth_result.identity,
            workspace_name=response_workspace_name,
        )
        if enforceable:
            filtered_payload = _backfill_mcp_search_response(
                filtered_payload,
                request_context=auth_result.request_context,
                authorizer=self.authorizer,
                identity=auth_result.identity,
                workspace_name=response_workspace_name,
            )
        if not enforceable:
            self._replace_json_response_payload(response, {})
        elif filtered_payload != payload:
            self._replace_json_response_payload(response, filtered_payload)

    async def _apply_response_authorization_filters(self, response, *, auth_result) -> None:
        response_workspace_name = None
        if isinstance(auth_result.request_context.workspace, str):
            response_workspace_name = auth_result.request_context.workspace.strip() or None
        if auth_result.rules[0].apply_workspace_filter and response.status_code < 400:
            await self._filter_workspace_list_response(response, auth_result=auth_result)
        await self._apply_collection_response_filters(
            response,
            auth_result=auth_result,
            response_workspace_name=response_workspace_name,
        )

    @staticmethod
    async def _read_json_response_payload(
        response,
    ) -> tuple[dict[str, object] | None, bytes | None]:
        """Consume a streaming Starlette response body and JSON-decode it.

        The consumed bytes are re-attached to ``response.body_iterator`` so
        downstream middleware can still read them.  Returns ``(None, None)`` when
        the response is not JSON, or ``(None, raw_bytes)`` on decode failure.
        """
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return None, None

        body = getattr(response, "body", None)
        if not isinstance(body, (bytes, bytearray)):
            collected = bytearray()
            async for chunk in response.body_iterator:
                collected.extend(chunk)
            body = bytes(collected)
            response.body_iterator = iterate_in_threadpool(iter([body]))
        else:
            body = bytes(body)

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, body
        if not isinstance(payload, dict):
            return None, body
        return payload, body

    @staticmethod
    def _replace_json_response_payload(response, payload: dict[str, object]) -> None:
        """Overwrite the response body with the re-serialized *payload*."""
        updated_body = json.dumps(payload).encode("utf-8")
        response.body = updated_body
        response.body_iterator = iterate_in_threadpool(iter([updated_body]))
        response.headers["content-length"] = str(len(updated_body))

    async def dispatch(self, request: Request, call_next):
        """Process each request through the authorization pipeline."""
        authorization_token = _AUTHORIZATION_HANDLED.set(None)
        try:
            state = request.scope.setdefault("state", {})
            state.setdefault(_REQUEST_RAW_BODY_STATE_KEY, b"")
            state.setdefault(_REQUEST_JSON_BODY_STATE_KEY, None)
            state.setdefault(_REQUEST_BODY_LOADED_STATE_KEY, False)
            canonical_path = _canonicalize_path(
                raw_path=str(request.url.path or ""),
                scope_path=request.scope.get("path"),
                root_path=request.scope.get("root_path"),
            )
            fastapi_app = request.scope.get("app")
            if fastapi_app is None:
                exc = MlflowException(
                    "FastAPI app missing from request scope.",
                    error_code=databricks_pb2.INTERNAL_ERROR,
                )
                return JSONResponse(
                    status_code=exc.get_http_status_code(),
                    content={"error": {"code": exc.error_code, "message": exc.message}},
                )

            # Skip authentication for unprotected paths
            if _is_unprotected_path(canonical_path):
                return await call_next(request)

            resolved_workspace_name = (
                workspace_context.get_request_workspace()
                if self.config_values.workspaces_enabled
                else self.config_values.namespace
            )
            workspace_set = False

            if self.config_values.workspaces_enabled and resolved_workspace_name is None:
                # FastAPI executes middlewares in reverse order, so this auth middleware can run
                # before the MLflow workspace middleware. Resolve here using the same helper, which
                # also falls back to the configured default workspace when the header is missing
                # or empty.
                try:
                    workspace = resolve_workspace_from_header(
                        request.headers.get(WORKSPACE_HEADER_NAME)
                    )
                except MlflowException as exc:
                    return JSONResponse(
                        status_code=exc.get_http_status_code(),
                        content=json.loads(exc.serialize_as_json()),
                    )

                if workspace is not None:
                    resolved_workspace_name = workspace.name
                    workspace_context.set_server_request_workspace(resolved_workspace_name)
                    workspace_set = True

            path_params = cast(
                dict[str, object],
                _extract_path_params(canonical_path, request.method) or dict(request.path_params),
            )

            async def _ensure_auth_request_json_body():
                await self._ensure_request_json_body(request)
                return state.get(_REQUEST_JSON_BODY_STATE_KEY)

            auth_request = build_fastapi_authorization_request(
                request,
                self.config_values,
                path=canonical_path,
                workspace=resolved_workspace_name,
                json_body=state.get(_REQUEST_JSON_BODY_STATE_KEY),
                path_params=path_params,
                ensure_json_body=_ensure_auth_request_json_body,
            )

            try:
                auth_result = await _authorize_request_async(
                    auth_request,
                    authorizer=self.authorizer,
                    config_values=self.config_values,
                )
                _AUTHORIZATION_HANDLED.set(auth_result)
                graphql_authorizer_token = _GRAPHQL_AUTHORIZER.set(self.authorizer)
            except MlflowException as exc:
                if workspace_set:
                    workspace_context.clear_server_request_workspace()
                return JSONResponse(
                    status_code=exc.get_http_status_code(),
                    content={"error": {"code": exc.error_code, "message": exc.message}},
                )
            self._apply_request_context_rewrites(
                request,
                original_request_context=auth_request,
                updated_request_context=auth_result.request_context,
                username=auth_result.username,
                override_run_user=auth_result.rules[0].override_run_user,
            )

            # Continue with the request, clearing any temporary workspace context.
            try:
                response = await call_next(request)
            finally:
                if workspace_set:
                    workspace_context.clear_server_request_workspace()
                _GRAPHQL_AUTHORIZER.reset(graphql_authorizer_token)
            await self._apply_response_authorization_filters(response, auth_result=auth_result)
            apply_response_cache_updates(
                auth_result.request_context,
                auth_result.rules,
                status_code=response.status_code,
            )
            return response
        finally:
            _AUTHORIZATION_HANDLED.reset(authorization_token)


def _registered_graphql_auth_middleware():
    authorizer = _GRAPHQL_AUTHORIZER.get()
    if authorizer is None:
        return []
    return _get_graphql_authorization_middleware(authorizer)


def create_app(app: Flask | None = None):
    """Enable Kubernetes-based authorization for the MLflow tracking server."""
    if app is None:
        app = mlflow_app

    parent_logger = getattr(app, "logger", logging.getLogger("mlflow"))
    core_mod._logger = parent_logger
    core_mod._logger.info("Kubernetes authorization plugin initialized")

    config_values = KubernetesAuthConfig.from_env()
    authorizer = KubernetesAuthorizer(config_values=config_values)
    atexit.register(authorizer.close)
    mlflow_handlers._get_graphql_auth_middleware = cast(Any, _registered_graphql_auth_middleware)

    _compile_authorization_rules()
    fastapi_app = create_fastapi_app(app)
    fastapi_app.add_middleware(
        KubernetesAuthMiddleware,
        authorizer=authorizer,
        config_values=config_values,
    )
    _validate_fastapi_route_authorization(fastapi_app)
    _validate_graphql_field_authorization()
    return fastapi_app


__all__ = ["KubernetesAuthMiddleware", "create_app"]
