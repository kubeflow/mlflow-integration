"""Compatibility helpers for MLflow-version-dependent workspace surfaces."""

from __future__ import annotations

from typing import Any

import mlflow
from packaging.version import Version

MLFLOW_VERSION = Version(mlflow.__version__)
HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE = MLFLOW_VERSION >= Version("3.13.0.dev0")

if HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE:
    from mlflow.entities.workspace import TraceArchivalConfig
    from mlflow.store.workspace.abstract_store import ResolvedTraceArchivalConfig
else:  # pragma: no cover - exercised via MLflow version matrix
    TraceArchivalConfig = Any
    ResolvedTraceArchivalConfig = Any

__all__ = [
    "HAS_MLFLOW_3_13_TRACE_ARCHIVAL_SURFACE",
    "MLFLOW_VERSION",
    "ResolvedTraceArchivalConfig",
    "TraceArchivalConfig",
]
