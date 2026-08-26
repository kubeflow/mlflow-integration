"""Kind-based functional coverage for the chart-owned MLflow deployment.

Run explicitly with ``MLFLOW_INTEGRATION=1`` after a cluster and image have
been prepared.  The test harness owns only generic Kubernetes resources and
can therefore be reused by any deployment of this chart.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

NAMESPACE = os.environ.get("MLFLOW_TEST_NAMESPACE", "mlflow-tests")
WORKSPACE_A = os.environ.get("MLFLOW_TEST_WORKSPACE_A", "mlflow-workspace-a")
WORKSPACE_B = os.environ.get("MLFLOW_TEST_WORKSPACE_B", "mlflow-workspace-b")
HIDDEN_WORKSPACE = os.environ.get("MLFLOW_TEST_HIDDEN_WORKSPACE", "mlflow-workspace-hidden")
EDIT_SERVICE_ACCOUNT = "workspace-a-edit"
EDIT_B_SERVICE_ACCOUNT = "workspace-b-edit"
VIEW_SERVICE_ACCOUNT = "workspace-a-view"
IMAGE = os.environ.get("MLFLOW_TEST_IMAGE", "mlflow-integration:test")
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")
CLIENT_FILE = Path(__file__).with_name("pod_client.py")


def kubectl(
    *args: str, input_text: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def apply_resources() -> None:
    manifest = f"""
apiVersion: v1
kind: Namespace
metadata:
  name: {NAMESPACE}
---
apiVersion: v1
kind: Namespace
metadata:
  name: {WORKSPACE_A}
  labels:
    mlflow-enabled: "true"
---
apiVersion: v1
kind: Namespace
metadata:
  name: {WORKSPACE_B}
  labels:
    mlflow-enabled: "true"
---
apiVersion: v1
kind: Namespace
metadata:
  name: {HIDDEN_WORKSPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {EDIT_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {VIEW_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {EDIT_B_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: mlflow-workspace-edit
  namespace: {WORKSPACE_A}
rules:
- apiGroups: ["mlflow.kubeflow.org"]
  resources: ["experiments", "registeredmodels"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: mlflow-workspace-view
  namespace: {WORKSPACE_A}
rules:
- apiGroups: ["mlflow.kubeflow.org"]
  resources: ["experiments", "registeredmodels"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: workspace-a-edit
  namespace: {WORKSPACE_A}
subjects:
- kind: ServiceAccount
  name: {EDIT_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: mlflow-workspace-edit
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: workspace-a-view
  namespace: {WORKSPACE_A}
subjects:
- kind: ServiceAccount
  name: {VIEW_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: mlflow-workspace-view
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: mlflow-workspace-edit
  namespace: {WORKSPACE_B}
rules:
- apiGroups: ["mlflow.kubeflow.org"]
  resources: ["experiments", "registeredmodels"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: workspace-b-edit
  namespace: {WORKSPACE_B}
subjects:
- kind: ServiceAccount
  name: {EDIT_B_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: mlflow-workspace-edit
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: mlflow-workspace-discovery
rules:
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["mlflow.kubeflow.org"]
  resources: ["mlflowconfigs"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: workspace-a-discovery
subjects:
- kind: ServiceAccount
  name: {EDIT_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
- kind: ServiceAccount
  name: {EDIT_B_SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: mlflow-workspace-discovery
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: unprivileged
  namespace: {NAMESPACE}
"""
    kubectl("apply", "-f", "-", input_text=manifest)
    configmap = kubectl(
        "create",
        "configmap",
        "mlflow-integration-client",
        f"--from-file=client.py={CLIENT_FILE}",
        "--namespace",
        NAMESPACE,
        "--dry-run=client",
        "-o",
        "yaml",
    ).stdout
    kubectl("apply", "-f", "-", input_text=configmap)


def run_pod(
    name: str,
    service_account: str,
    workspace: str,
    *,
    denied: bool = False,
    scenario: str = "tracking",
) -> str:
    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": NAMESPACE},
        "spec": {
            "restartPolicy": "Never",
            "serviceAccountName": service_account,
            "containers": [
                {
                    "name": "client",
                    "image": IMAGE,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["python", "/opt/integration/client.py"],
                    "env": [
                        {"name": "MLFLOW_TRACKING_URI", "value": TRACKING_URI},
                        {"name": "MLFLOW_WORKSPACE", "value": workspace},
                        {"name": "EXPECTED_DENIED", "value": str(denied).lower()},
                        {"name": "SCENARIO", "value": scenario},
                        {"name": "SOURCE_WORKSPACE", "value": WORKSPACE_A},
                        {"name": "EXCLUDED_WORKSPACE", "value": HIDDEN_WORKSPACE},
                        {
                            "name": "MLFLOW_K8S_WORKSPACE_LABEL_SELECTOR",
                            "value": "mlflow-enabled=true",
                        },
                    ],
                    "volumeMounts": [{"name": "client", "mountPath": "/opt/integration"}],
                }
            ],
            "volumes": [{"name": "client", "configMap": {"name": "mlflow-integration-client"}}],
        },
    }
    kubectl("apply", "-f", "-", input_text=json.dumps(manifest))
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        phase = kubectl(
            "get", "pod", name, "--namespace", NAMESPACE, "-o", "jsonpath={.status.phase}"
        ).stdout
        if phase == "Succeeded":
            break
        if phase == "Failed":
            logs = kubectl("logs", f"pod/{name}", "--namespace", NAMESPACE, check=False)
            pytest.fail(f"pod {name} failed:\n{logs.stdout}\n{logs.stderr}")
        time.sleep(1)
    else:
        logs = kubectl("logs", f"pod/{name}", "--namespace", NAMESPACE, check=False)
        pytest.fail(f"pod {name} did not succeed:\n{logs.stdout}\n{logs.stderr}")
    return kubectl("logs", f"pod/{name}", "--namespace", NAMESPACE).stdout


@pytest.fixture(scope="session", autouse=True)
def kind_resources() -> Generator[None, None, None]:
    if os.environ.get("MLFLOW_INTEGRATION") != "1":
        pytest.skip("set MLFLOW_INTEGRATION=1 to run live Kubernetes tests")
    kubectl("version", "--client")
    apply_resources()
    yield
    for name in (
        "workspace-discovery",
        "health-client",
        "allowed-client",
        "view-seed",
        "workspace-b-seed",
        "view-client",
        "cross-workspace-client",
        "denied-client",
    ):
        kubectl("delete", "pod", name, "--namespace", NAMESPACE, "--ignore-not-found")
    kubectl(
        "delete",
        "configmap",
        "mlflow-integration-client",
        "--namespace",
        NAMESPACE,
        "--ignore-not-found",
    )


def test_health_endpoint() -> None:
    logs = run_pod("health-client", EDIT_SERVICE_ACCOUNT, WORKSPACE_A, scenario="health")
    assert "health scenario passed" in logs


def test_workspace_discovery_from_pod() -> None:
    logs = run_pod("workspace-discovery", EDIT_SERVICE_ACCOUNT, WORKSPACE_A, scenario="workspaces")
    assert "workspace discovery passed" in logs


def test_tracking_and_artifacts_from_pod() -> None:
    logs = run_pod("allowed-client", EDIT_SERVICE_ACCOUNT, WORKSPACE_A)
    assert "allowed scenario passed" in logs


def test_view_role_cannot_mutate_from_pod() -> None:
    run_pod("view-seed", EDIT_SERVICE_ACCOUNT, WORKSPACE_A)
    logs = run_pod("view-client", VIEW_SERVICE_ACCOUNT, WORKSPACE_A, scenario="view")
    assert "view scenario passed" in logs


def test_cross_workspace_access_is_denied() -> None:
    run_pod("workspace-b-seed", EDIT_B_SERVICE_ACCOUNT, WORKSPACE_B)
    logs = run_pod(
        "cross-workspace-client",
        EDIT_SERVICE_ACCOUNT,
        WORKSPACE_B,
        scenario="cross-workspace",
    )
    assert "cross-workspace scenario passed" in logs


def test_unprivileged_access_is_denied() -> None:
    logs = run_pod("denied-client", "unprivileged", WORKSPACE_A, denied=True)
    assert "denied scenario passed" in logs
