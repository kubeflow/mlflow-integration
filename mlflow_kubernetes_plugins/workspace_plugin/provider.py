from __future__ import annotations

import logging
import os
import posixpath
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Iterable, TypedDict
from urllib.parse import parse_qs, urlparse

from kubernetes import client, config
from kubernetes.client import CoreV1Api, CustomObjectsApi
from kubernetes.config.config_exception import ConfigException
from mlflow.entities.workspace import Workspace, WorkspaceDeletionMode
from mlflow.exceptions import MlflowException
from mlflow.protos import databricks_pb2
from mlflow.protos.databricks_pb2 import (
    INVALID_PARAMETER_VALUE,
    INVALID_STATE,
    RESOURCE_DOES_NOT_EXIST,
)
from mlflow.store.workspace.abstract_store import AbstractStore
from mlflow.utils.uri import append_to_uri_path

from mlflow_kubernetes_plugins.workspace_plugin._compat import (
    HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE,
)
from mlflow_kubernetes_plugins.workspace_plugin.caches import (
    ARCHIVE_CONNECTION_SECRET_NAME,
    ARTIFACT_CONNECTION_SECRET_NAME,
    MlflowConfigCache,
    NamespaceCache,
    SecretCache,
)

_logger = logging.getLogger(__name__)
DEFAULT_NAMESPACE_EXCLUDE_GLOBS: tuple[str, ...] = (
    "dedicated-admin",
    "kube-*",
    "nvidia-gpu-operator",
    "open-cluster-management",
    "open-cluster-management-*",
    "openshift-*",
    "openshift",
    "redhat-ods-*",
)


def _parse_glob_input(value: Iterable[str] | str | None) -> tuple[str, ...] | None:
    if value is None:
        return None

    candidates = value.split(",") if isinstance(value, str) else value
    return tuple(token.strip() for token in candidates if token and token.strip())


def _merge_globs(
    *glob_lists: tuple[str, ...] | None,
) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []

    for glob_list in glob_lists:
        if not glob_list:
            continue
        for pattern in glob_list:
            if pattern in seen:
                continue
            merged.append(pattern)
            seen.add(pattern)

    return tuple(merged)


class WorkspaceURIOptions(TypedDict):
    label_selector: str | None
    default_workspace: str | None
    namespace_exclude_globs: tuple[str, ...] | None


def _build_workspace(
    *,
    name: str,
    description: str | None,
    default_artifact_root: str | None,
    trace_archival_location: str | None = None,
    trace_archival_retention: str | None = None,
) -> Workspace:
    kwargs: dict[str, str | None] = {
        "name": name,
        "description": description,
        "default_artifact_root": default_artifact_root,
    }
    if HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE:
        kwargs["trace_archival_location"] = trace_archival_location
        kwargs["trace_archival_retention"] = trace_archival_retention
    return Workspace(**kwargs)


@dataclass(frozen=True, slots=True)
class KubernetesWorkspaceProviderConfig:
    label_selector: str | None = None
    default_workspace: str | None = None
    namespace_exclude_globs: tuple[str, ...] = DEFAULT_NAMESPACE_EXCLUDE_GLOBS

    @classmethod
    def from_sources(
        cls,
        *,
        label_selector: str | None = None,
        default_workspace: str | None = None,
        namespace_exclude_globs: Iterable[str] | str | None = None,
    ) -> "KubernetesWorkspaceProviderConfig":
        env = os.environ

        env_globs = _parse_glob_input(env.get("MLFLOW_K8S_NAMESPACE_EXCLUDE_GLOBS"))

        if namespace_exclude_globs is not None:
            glob_source = _parse_glob_input(namespace_exclude_globs) or ()
        elif env_globs is not None:
            glob_source = env_globs
        else:
            glob_source = ()

        exclude_globs = _merge_globs(DEFAULT_NAMESPACE_EXCLUDE_GLOBS, glob_source)

        return cls(
            label_selector=label_selector or env.get("MLFLOW_K8S_WORKSPACE_LABEL_SELECTOR"),
            default_workspace=default_workspace or env.get("MLFLOW_K8S_DEFAULT_WORKSPACE"),
            namespace_exclude_globs=exclude_globs,
        )


class KubernetesWorkspaceProvider(AbstractStore):
    """Workspace provider that maps MLflow workspaces to Kubernetes namespaces."""

    def __init__(
        self,
        tracking_uri: str | None = None,
        *,
        label_selector: str | None = None,
        default_workspace: str | None = None,
        namespace_exclude_globs: Iterable[str] | str | None = None,
    ) -> None:
        del tracking_uri  # Unused but kept for compatibility with MLflow factory

        self._config = KubernetesWorkspaceProviderConfig.from_sources(
            label_selector=label_selector,
            default_workspace=default_workspace,
            namespace_exclude_globs=namespace_exclude_globs,
        )

        self._core_api, self._custom_api = self._create_api_clients()
        self._secret_cache: SecretCache | None = None
        self._secret_cache_lock = threading.Lock()
        self._archive_secret_cache: SecretCache | None = None
        self._archive_secret_cache_lock = threading.Lock()
        self._namespace_cache = NamespaceCache(
            self._core_api,
            self._config.label_selector,
            self._config.namespace_exclude_globs,
        )
        self._mlflow_config_cache = MlflowConfigCache(
            self._custom_api,
            ensure_artifact_connection_secret_cache=self._ensure_secret_cache,
            ensure_archive_connection_secret_cache=(
                self._ensure_archive_secret_cache
                if HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE
                else None
            ),
        )

    def list_workspaces(self) -> Iterable[Workspace]:  # type: ignore[override]
        infos = self._namespace_cache.list_namespaces()
        return [
            _build_workspace(
                name=info.name,
                description=info.description,
                default_artifact_root=self._resolve_workspace_artifact_root(info.name),
                trace_archival_location=self._resolve_workspace_trace_archival_location(info.name),
                trace_archival_retention=self._resolve_workspace_trace_archival_retention(
                    info.name
                ),
            )
            for info in infos
        ]

    def get_workspace(self, workspace_name: str) -> Workspace:  # type: ignore[override]
        info = self._namespace_cache.get_namespace(workspace_name)
        if info is None:
            parts = [
                f"Workspace '{workspace_name}' not found in the Kubernetes cluster.",
                "Each MLflow workspace maps 1:1 to a namespace.",
            ]
            if self._config.label_selector:
                parts.append(
                    f"Ensure the namespace exists and matches the configured selector "
                    f"('{self._config.label_selector}')."
                )
            raise MlflowException(" ".join(parts), RESOURCE_DOES_NOT_EXIST)

        return _build_workspace(
            name=info.name,
            description=info.description,
            default_artifact_root=self._resolve_workspace_artifact_root(info.name),
            trace_archival_location=self._resolve_workspace_trace_archival_location(info.name),
            trace_archival_retention=self._resolve_workspace_trace_archival_retention(info.name),
        )

    def create_workspace(self, workspace: Workspace) -> Workspace:  # type: ignore[override]
        raise NotImplementedError("Namespace creation is not supported by this provider")

    def update_workspace(self, workspace: Workspace) -> Workspace:  # type: ignore[override]
        raise NotImplementedError("Namespace updates are not supported by this provider")

    def delete_workspace(
        self,
        workspace_name: str,
        mode: WorkspaceDeletionMode = WorkspaceDeletionMode.RESTRICT,
    ) -> None:  # type: ignore[override]
        del mode
        raise NotImplementedError("Namespace deletion is not supported by this provider")

    def get_default_workspace(self) -> Workspace:  # type: ignore[override]
        if not self._config.default_workspace:
            raise NotImplementedError(
                "Active workspace is required. Specify one in the request path or set "
                "MLFLOW_K8S_DEFAULT_WORKSPACE."
            )
        return self.get_workspace(self._config.default_workspace)

    def _resolve_workspace_artifact_root(self, workspace_name: str) -> str | None:
        """Best-effort resolution of the per-workspace artifact root."""
        try:
            root, should_append = self.resolve_artifact_root(None, workspace_name)
        except MlflowException as exc:
            if exc.error_code == databricks_pb2.ErrorCode.Name(INVALID_PARAMETER_VALUE):
                _logger.warning(
                    "Artifact root configuration error for workspace '%s': %s",
                    workspace_name,
                    exc,
                )
                return None
            raise
        if should_append:
            return None
        return root

    def _resolve_workspace_trace_archival_location(self, workspace_name: str) -> str | None:
        """Best-effort resolution of the per-workspace archive root override."""
        if not HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE:
            return None

        mlflow_config = self._mlflow_config_cache.get_config(workspace_name)
        if not mlflow_config or (
            not mlflow_config.archive_root_secret and not mlflow_config.archive_root_path
        ):
            return None

        try:
            return self._resolve_secret_backed_root(
                workspace_name=workspace_name,
                configured_secret=mlflow_config.archive_root_secret,
                configured_path=mlflow_config.archive_root_path,
                supported_secret_name=ARCHIVE_CONNECTION_SECRET_NAME,
                path_field_name="archiveRootPath",
                secret_field_name="archiveRootSecret",
                location_kind="trace archival",
                secret_cache_factory=self._ensure_archive_secret_cache,
            )
        except MlflowException as exc:
            if exc.error_code == databricks_pb2.ErrorCode.Name(INVALID_PARAMETER_VALUE):
                _logger.warning(
                    "Trace archival configuration error for workspace '%s': %s",
                    workspace_name,
                    exc,
                )
                return None
            raise

    def _resolve_workspace_trace_archival_retention(self, workspace_name: str) -> str | None:
        """Best-effort resolution of the per-workspace archive retention override."""
        if not HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE:
            return None

        mlflow_config = self._mlflow_config_cache.get_config(workspace_name)
        if not mlflow_config or mlflow_config.trace_archival_retention is None:
            return None

        from mlflow.utils.validation import _validate_trace_archival_retention_string

        try:
            return _validate_trace_archival_retention_string(
                mlflow_config.trace_archival_retention,
                parameter_name="traceArchivalRetention",
            )
        except MlflowException as exc:
            if exc.error_code == databricks_pb2.ErrorCode.Name(INVALID_PARAMETER_VALUE):
                _logger.warning(
                    "Trace archival retention configuration error for workspace '%s': %s",
                    workspace_name,
                    exc,
                )
                return None
            raise

    def resolve_artifact_root(
        self, default_artifact_root: str | None, workspace_name: str
    ) -> tuple[str | None, bool]:
        """
        Resolve the artifact root for a workspace.

        If an MLflowConfig CRD exists for the namespace with artifactRootSecret set,
        resolve the bucket information from the shared Secret cache and construct the
        artifact root. If artifactRootPath is also set, append it to the bucket URI.

        Returns:
            A tuple (artifact_root, should_append_workspace_prefix).
        """
        if not workspace_name:
            return default_artifact_root, True

        mlflow_config = self._mlflow_config_cache.get_config(workspace_name)
        if not mlflow_config or not mlflow_config.artifact_root_secret:
            # No override configured - use default behavior
            return default_artifact_root, True

        return (
            self._resolve_secret_backed_root(
                workspace_name=workspace_name,
                configured_secret=mlflow_config.artifact_root_secret,
                configured_path=mlflow_config.artifact_root_path,
                supported_secret_name=ARTIFACT_CONNECTION_SECRET_NAME,
                path_field_name="artifactRootPath",
                secret_field_name="artifactRootSecret",
                location_kind="artifact storage",
                secret_cache_factory=self._ensure_secret_cache,
            ),
            False,
        )

    def resolve_trace_archival_config(
        self,
        default_trace_archival_root: str,
        default_retention: str,
        workspace_name: str,
    ):
        if not HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE:
            raise NotImplementedError("Trace archival workspace overrides require MLflow 3.13+.")

        from mlflow.entities.workspace import TraceArchivalConfig
        from mlflow.store.workspace.abstract_store import ResolvedTraceArchivalConfig
        from mlflow.utils.validation import _validate_trace_archival_retention_string

        resolved_root = default_trace_archival_root
        resolved_retention = default_retention
        append_workspace_prefix = True

        if workspace_name:
            mlflow_config = self._mlflow_config_cache.get_config(workspace_name)
            if mlflow_config:
                if mlflow_config.archive_root_secret or mlflow_config.archive_root_path:
                    resolved_root = self._resolve_secret_backed_root(
                        workspace_name=workspace_name,
                        configured_secret=mlflow_config.archive_root_secret,
                        configured_path=mlflow_config.archive_root_path,
                        supported_secret_name=ARCHIVE_CONNECTION_SECRET_NAME,
                        path_field_name="archiveRootPath",
                        secret_field_name="archiveRootSecret",
                        location_kind="trace archival",
                        secret_cache_factory=self._ensure_archive_secret_cache,
                    )
                    append_workspace_prefix = False
                if mlflow_config.trace_archival_retention is not None:
                    resolved_retention = _validate_trace_archival_retention_string(
                        mlflow_config.trace_archival_retention,
                        parameter_name="traceArchivalRetention",
                    )

        return ResolvedTraceArchivalConfig(
            config=TraceArchivalConfig(
                location=resolved_root,
                retention=resolved_retention,
            ),
            append_workspace_prefix=append_workspace_prefix,
        )

    def _resolve_secret_backed_root(
        self,
        *,
        workspace_name: str,
        configured_secret: str | None,
        configured_path: str | None,
        supported_secret_name: str,
        path_field_name: str,
        secret_field_name: str,
        location_kind: str,
        secret_cache_factory: Callable[[], SecretCache],
    ) -> str:
        if not configured_secret:
            if configured_path:
                raise MlflowException(
                    f"MLflowConfig in namespace '{workspace_name}' sets {path_field_name} "
                    f"without {secret_field_name}.",
                    INVALID_PARAMETER_VALUE,
                )
            raise MlflowException(
                f"MLflowConfig in namespace '{workspace_name}' is missing {secret_field_name}.",
                INVALID_PARAMETER_VALUE,
            )

        if configured_secret != supported_secret_name:
            raise MlflowException(
                f"MLflowConfig in namespace '{workspace_name}' sets {secret_field_name} to "
                f"'{configured_secret}', but only '{supported_secret_name}' is supported.",
                INVALID_PARAMETER_VALUE,
            )

        secret_cache = secret_cache_factory()
        secret_info = secret_cache.get_secret(workspace_name)
        bucket_uri = secret_info.bucket_uri if secret_info else None

        if not bucket_uri:
            raise MlflowException(
                f"Invalid {location_kind} configuration in namespace '{workspace_name}'. "
                f"Secret '{supported_secret_name}' does not exist or is missing the "
                "'AWS_S3_BUCKET' key.",
                INVALID_PARAMETER_VALUE,
            )

        if configured_path:
            path = configured_path.strip()
            if not path:
                _logger.debug(
                    "MLflowConfig in namespace '%s' has empty %s. Using bucket root.",
                    workspace_name,
                    path_field_name,
                )
            elif validated_path := self._validate_relative_path(
                path,
                workspace_name,
                path_field_name,
            ):
                bucket_uri = append_to_uri_path(bucket_uri, validated_path)

        return bucket_uri

    def _validate_artifact_path(
        self,
        path: str,
        workspace_name: str,
        field_name: str = "artifactRootPath",
    ) -> str | None:
        return self._validate_relative_path(path, workspace_name, field_name)

    def _validate_relative_path(
        self,
        path: str,
        workspace_name: str,
        field_name: str,
    ) -> str | None:
        """
        Validate and normalize an artifact path.

        Args:
            path: The raw artifact path from MLflowConfig.
            workspace_name: The namespace name (for error messages).

        Returns:
            The validated and normalized path, or None if path is empty after normalization.

        Raises:
            MlflowException: If path contains invalid characters or traversal attempts.
        """
        # Reject backslashes
        if "\\" in path:
            raise MlflowException(
                f"Invalid {field_name} '{path}' in MLflowConfig for namespace "
                f"'{workspace_name}'. Backslashes are not allowed; use forward slashes.",
                INVALID_PARAMETER_VALUE,
            )

        # Normalize the path to resolve . and .. segments
        normalized = posixpath.normpath(path)

        # Reject absolute paths
        if normalized.startswith("/"):
            raise MlflowException(
                f"Invalid {field_name} '{path}' in MLflowConfig for namespace "
                f"'{workspace_name}'. Absolute paths are not allowed.",
                INVALID_PARAMETER_VALUE,
            )

        # This catches cases like "../foo" that normalize but still traverse up
        if normalized == ".." or normalized.startswith("../") or "/../" in normalized:
            raise MlflowException(
                f"Invalid {field_name} '{path}' in MLflowConfig for namespace "
                f"'{workspace_name}'. Path traversal ('..') is not allowed.",
                INVALID_PARAMETER_VALUE,
            )

        if normalized == ".":
            return None

        return normalized

    def _ensure_secret_cache(self) -> SecretCache:
        """Create the shared SecretCache once, then reuse it."""
        cache = self._secret_cache
        if cache is not None:
            return cache

        with self._secret_cache_lock:
            cache = self._secret_cache
            if cache is None:
                cache = SecretCache(
                    self._core_api,
                    ARTIFACT_CONNECTION_SECRET_NAME,
                    "artifact root",
                )
                self._secret_cache = cache

        return cache

    def _ensure_archive_secret_cache(self) -> SecretCache:
        """Create the shared archive SecretCache once, then reuse it."""
        cache = self._archive_secret_cache
        if cache is not None:
            return cache

        with self._archive_secret_cache_lock:
            cache = self._archive_secret_cache
            if cache is None:
                cache = SecretCache(
                    self._core_api,
                    ARCHIVE_CONNECTION_SECRET_NAME,
                    "trace archival root",
                )
                self._archive_secret_cache = cache

        return cache

    @staticmethod
    def _create_api_clients() -> tuple[CoreV1Api, CustomObjectsApi]:
        """Load Kubernetes config and create API clients."""
        try:
            config.load_incluster_config()
        except ConfigException:
            try:
                config.load_kube_config()
            except ConfigException as exc:  # pragma: no cover - depends on env
                raise MlflowException(
                    "Failed to load Kubernetes configuration for workspace provider",
                    error_code=INVALID_STATE,
                ) from exc
        return client.CoreV1Api(), client.CustomObjectsApi()


def _parse_workspace_uri_options(
    workspace_uri: str | None,
) -> WorkspaceURIOptions:
    """
    Parse query parameters from the workspace URI to configure the provider.
    Supported parameters:
      - label_selector
      - default_workspace
      - namespace_exclude_globs (comma-separated glob patterns)
    """

    if not workspace_uri:
        return {
            "label_selector": None,
            "default_workspace": None,
            "namespace_exclude_globs": None,
        }

    parsed = urlparse(workspace_uri)
    query = parse_qs(parsed.query, keep_blank_values=True)

    def _get_param(name: str) -> str | None:
        values = query.get(name) or []
        value = values[-1] if values else None
        if value is None:
            return None
        value = value.strip()
        return value or None

    options: WorkspaceURIOptions = {
        "label_selector": _get_param("label_selector"),
        "default_workspace": _get_param("default_workspace"),
        "namespace_exclude_globs": None,
    }

    exclude_param = _get_param("namespace_exclude_globs")
    if exclude_param is not None:
        parsed_excludes = _parse_glob_input(exclude_param) or ()
        options["namespace_exclude_globs"] = parsed_excludes
    else:
        options["namespace_exclude_globs"] = None

    return options


def create_kubernetes_workspace_store(workspace_uri: str, **_kwargs) -> KubernetesWorkspaceProvider:
    """
    Entry point factory that instantiates the Kubernetes workspace provider.

    Args:
        workspace_uri: The resolved workspace store URI. Query parameters are used
            to override provider configuration.
        _kwargs: Additional keyword arguments ignored for forward compatibility.
    """

    options = _parse_workspace_uri_options(workspace_uri)
    return KubernetesWorkspaceProvider(
        tracking_uri=workspace_uri,
        label_selector=options.get("label_selector"),
        default_workspace=options.get("default_workspace"),
        namespace_exclude_globs=options.get("namespace_exclude_globs"),
    )
