"""SDK scenario executed inside a Kubernetes pod.

The script deliberately uses the public MLflow client APIs.  The pod receives its
ServiceAccount token from the projected token file, which exercises the same
in-cluster path used by applications.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import urllib.request

import mlflow
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

URI = os.environ["MLFLOW_TRACKING_URI"]
TOKEN = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount/token").read_text().strip()
WORKSPACE = os.environ["MLFLOW_WORKSPACE"]
EXPECTED_DENIED = os.environ.get("EXPECTED_DENIED", "false").lower() == "true"
SCENARIO = os.environ.get("SCENARIO", "tracking")


def client() -> MlflowClient:
    return MlflowClient(tracking_uri=URI, workspace_store_uri="kubernetes://")


def _get_or_create_experiment(current: MlflowClient, name: str) -> str:
    existing = current.get_experiment_by_name(name)
    if existing is not None:
        return existing.experiment_id
    return current.create_experiment(name)


def _get_or_create_model(current: MlflowClient, name: str) -> None:
    try:
        current.get_registered_model(name)
    except MlflowException:
        current.create_registered_model(name)


def run_allowed_scenario() -> None:
    mlflow.set_tracking_uri(URI)
    os.environ["MLFLOW_TRACKING_TOKEN"] = TOKEN
    mlflow.set_workspace(WORKSPACE)

    current = client()
    experiment_name = f"integration-{WORKSPACE}"
    model_name = f"integration-model-{WORKSPACE}"
    experiment_id = _get_or_create_experiment(current, experiment_name)
    _get_or_create_model(current, model_name)
    run = current.create_run(experiment_id)
    run_id = run.info.run_id
    current.log_metric(run_id, "accuracy", 0.9, step=1)
    current.log_param(run_id, "workspace", WORKSPACE)
    current.set_tag(run_id, "scenario", "kind")
    with tempfile.TemporaryDirectory() as directory:
        artifact = pathlib.Path(directory) / "result.txt"
        artifact.write_text(f"workspace={WORKSPACE}\n", encoding="utf-8")
        current.log_artifact(run_id, str(artifact))
        downloaded = pathlib.Path(directory) / "downloaded"
        current.download_artifacts(run_id, "result.txt", str(downloaded))
        assert (downloaded / "result.txt").read_text(encoding="utf-8") == artifact.read_text(
            encoding="utf-8"
        )

    fetched = current.get_run(run_id)
    assert fetched.data.metrics["accuracy"] == 0.9
    assert fetched.data.params["workspace"] == WORKSPACE
    assert fetched.data.tags["scenario"] == "kind"
    assert any(run.info.run_id == run_id for run in current.search_runs([experiment_id]))
    assert current.get_registered_model(model_name).name == model_name
    assert any(item.name == model_name for item in current.search_registered_models())
    print(f"allowed scenario passed for {WORKSPACE}")


def _assert_denied(operation) -> None:
    try:
        operation()
    except MlflowException as exc:
        assert "PERMISSION_DENIED" in str(exc) or "Permission denied" in str(exc)
        return
    raise AssertionError("a restricted ServiceAccount unexpectedly accessed MLflow")


def _assert_denied_or_empty(operation) -> None:
    try:
        result = operation()
    except MlflowException as exc:
        assert "PERMISSION_DENIED" in str(exc) or "Permission denied" in str(exc)
        return
    assert not result, "an unauthorized collection returned visible MLflow objects"


def run_view_scenario() -> None:
    mlflow.set_tracking_uri(URI)
    os.environ["MLFLOW_TRACKING_TOKEN"] = TOKEN
    mlflow.set_workspace(WORKSPACE)
    current = client()
    experiment_name = f"integration-{WORKSPACE}"
    model_name = f"integration-model-{WORKSPACE}"

    experiment = current.get_experiment_by_name(experiment_name)
    assert experiment is not None
    assert any(item.name == experiment_name for item in current.search_experiments())
    assert current.get_registered_model(model_name).name == model_name
    assert any(item.name == model_name for item in current.search_registered_models())

    _assert_denied(lambda: current.create_experiment(f"view-must-not-create-{WORKSPACE}"))
    _assert_denied(lambda: current.create_registered_model(f"view-must-not-create-{WORKSPACE}"))
    _assert_denied(lambda: current.create_run(experiment.experiment_id))
    _assert_denied(lambda: current.delete_experiment(experiment.experiment_id))
    _assert_denied(lambda: current.delete_registered_model(model_name))
    print("view scenario passed")


def run_cross_workspace_scenario() -> None:
    mlflow.set_tracking_uri(URI)
    os.environ["MLFLOW_TRACKING_TOKEN"] = TOKEN
    mlflow.set_workspace(WORKSPACE)
    current = client()
    source_experiment = f"integration-{os.environ.get('SOURCE_WORKSPACE', WORKSPACE)}"
    mlflow.set_workspace(WORKSPACE)
    try:
        experiments = current.search_experiments()
    except MlflowException as exc:
        assert "PERMISSION_DENIED" in str(exc) or "Permission denied" in str(exc)
    else:
        assert source_experiment not in {experiment.name for experiment in experiments}
    _assert_denied_or_empty(current.search_experiments)
    _assert_denied_or_empty(current.search_registered_models)
    _assert_denied(lambda: current.create_experiment(f"cross-must-not-create-{WORKSPACE}"))
    print("cross-workspace scenario passed")


def run_denied_scenario() -> None:
    mlflow.set_tracking_uri(URI)
    os.environ["MLFLOW_TRACKING_TOKEN"] = TOKEN
    mlflow.set_workspace(WORKSPACE)
    current = client()
    _assert_denied(lambda: current.create_experiment(f"should-be-denied-{WORKSPACE}"))
    _assert_denied_or_empty(lambda: client().search_experiments())
    _assert_denied(lambda: client().get_registered_model(f"integration-model-{WORKSPACE}"))
    print("denied scenario passed")


def run_workspace_scenario() -> None:
    os.environ["MLFLOW_TRACKING_TOKEN"] = TOKEN
    names = {workspace.name for workspace in client().list_workspaces()}
    assert WORKSPACE in names
    excluded = os.environ.get("EXCLUDED_WORKSPACE")
    if excluded:
        assert excluded not in names
    print(f"workspace discovery passed: {sorted(names)}")


def run_health_scenario() -> None:
    assert urllib.request.urlopen(f"{URI}/health").read() == b"OK"
    print("health scenario passed")


if __name__ == "__main__":
    if SCENARIO == "health":
        run_health_scenario()
    elif SCENARIO == "workspaces":
        run_workspace_scenario()
    elif SCENARIO == "view":
        run_view_scenario()
    elif SCENARIO == "cross-workspace":
        run_cross_workspace_scenario()
    elif EXPECTED_DENIED:
        run_denied_scenario()
    else:
        run_allowed_scenario()
