"""Keep the chart smoke test tied to the production image and checked-out plugin."""

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/helm-ci.yml"
WORKFLOW = yaml.load(WORKFLOW_PATH.read_text(), Loader=yaml.BaseLoader)


def test_production_image_installs_checked_out_plugin():
    instructions = [
        shlex.split(line)
        for line in (REPOSITORY_ROOT / "Dockerfile").read_text().splitlines()
        if line.strip()
    ]
    assert ["COPY", "pyproject.toml", "README.md", "LICENSE", "./"] in instructions
    assert ["COPY", "mlflow_kubernetes_plugins", "./mlflow_kubernetes_plugins"] in instructions
    installation = next(line for line in instructions if line[:3] == ["RUN", "pip", "install"])
    assert "." in installation
    assert "mlflow-kubernetes-plugins" not in installation


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_chart_workflow_tracks_image_inputs(event):
    paths = set(WORKFLOW["on"][event]["paths"])
    assert {
        "Dockerfile",
        ".dockerignore",
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "mlflow_kubernetes_plugins/**",
        "tests/test_helm_ci.py",
    } <= paths


def test_chart_smoke_builds_loads_and_installs_the_same_image(tmp_path):
    command_log = tmp_path / "commands.jsonl"
    command = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

with open(os.environ["COMMAND_LOG"], "a") as stream:
    stream.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + "\\n")
"""
    for name in ("docker", "kind", "helm", "kubectl"):
        executable = tmp_path / name
        executable.write_text(command)
        executable.chmod(0o755)

    job = WORKFLOW["jobs"]["kind-smoke-test"]
    assert job.get("env", {}).get("MLFLOW_TEST_IMAGE") == "mlflow-chart:${{ github.sha }}"
    steps = {step.get("name"): step for step in job["steps"]}
    for name in ("Build and load MLflow image", "Install MLflow chart"):
        assert name in steps
        subprocess.run(
            ["bash", "-e", "-c", steps[name]["run"]],
            cwd=REPOSITORY_ROOT,
            env={
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "COMMAND_LOG": str(command_log),
                "MLFLOW_TEST_IMAGE": "mlflow-chart:checked-out-commit",
            },
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    commands = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert commands[0] == ["docker", "build", "--tag", "mlflow-chart:checked-out-commit", "."]
    assert commands[1] == [
        "kind",
        "load",
        "docker-image",
        "mlflow-chart:checked-out-commit",
        "--name",
        "mlflow-chart",
    ]
    installation = commands[2]
    assert installation[:4] == ["helm", "upgrade", "--install", "mlflow"]
    assert "image.repository=mlflow-chart" in installation
    assert "image.tag=checked-out-commit" in installation
    assert "image.pullPolicy=Never" in installation
