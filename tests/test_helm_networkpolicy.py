"""Verify configurable ingress without changing standalone chart defaults."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1] / "charts/mlflow"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")


def render_policy(values):
    output = subprocess.run(
        [
            "helm",
            "template",
            "mlflow",
            str(CHART),
            "--set",
            "mlflow.backendStoreUri=sqlite:////mlflow/mlflow.db",
            "--values",
            "-",
        ],
        input=yaml.safe_dump(values),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return next(
        (
            resource
            for resource in yaml.safe_load_all(output)
            if resource and resource["kind"] == "NetworkPolicy"
        ),
        None,
    )


def test_network_policy_remains_disabled_by_default():
    assert render_policy({}) is None


def test_empty_ingress_preserves_standalone_reachability():
    policy = render_policy({"networkPolicy": {"enabled": True, "ingressRules": []}})
    assert {"namespaceSelector": {}} in policy["spec"]["ingress"][0]["from"]


def test_custom_ingress_replaces_default_and_preserves_egress():
    rules = [
        {
            "from": [{"namespaceSelector": {"matchLabels": {"team": "tracking"}}}],
            "ports": [{"port": 5000, "protocol": "TCP"}],
        }
    ]
    default = render_policy({"networkPolicy": {"enabled": True}})
    custom = render_policy({"networkPolicy": {"enabled": True, "ingressRules": rules}})
    assert custom["spec"]["ingress"] == rules
    assert custom["spec"]["egress"] == default["spec"]["egress"]
