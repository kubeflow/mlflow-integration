"""Cluster-free regression coverage for the disposable integration runner."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(tmp_path):
    commands = tmp_path / "commands.jsonl"
    executable = tmp_path / "command"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "name = pathlib.Path(sys.argv[0]).name\n"
        "arguments = sys.argv[1:]\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as stream:\n"
        "    stream.write(json.dumps([name, arguments, os.environ.get('KUBECONFIG')]) + '\\n')\n"
        "if name == 'kind' and arguments[:2] == ['get', 'clusters']:\n"
        "    print(os.environ.get('EXISTING_CLUSTER', ''))\n"
        "if name == os.environ.get('FAIL_COMMAND'):\n"
        "    sys.exit(17)\n"
    )
    executable.chmod(0o755)
    for name in ("kind", "kubectl", "helm", "docker", "podman", "uv"):
        (tmp_path / name).symlink_to(executable)

    def run(**settings):
        environment = {
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "COMMAND_LOG": str(commands),
            "KIND_CLUSTER_NAME": "runner-owned",
            "KUBECONFIG": str(tmp_path / "original-config"),
            "CONTAINER_TOOL": "docker",
            **settings,
        }
        result = subprocess.run(
            ["bash", str(ROOT / "hack/kind-e2e.sh")],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
        )
        recorded = (
            [json.loads(line) for line in commands.read_text().splitlines()]
            if commands.exists()
            else []
        )
        return result, recorded

    return run


@pytest.mark.parametrize("image", ["untagged", "registry:5000/image", "image:", "image@sha256:abc"])
def test_invalid_image_does_not_touch_cluster(runner, image):
    result, commands = runner(MLFLOW_TEST_IMAGE=image)
    assert result.returncode != 0
    assert not commands


def test_existing_cluster_is_never_modified(runner):
    result, commands = runner(EXISTING_CLUSTER="runner-owned")
    assert result.returncode != 0
    assert [(name, arguments) for name, arguments, _ in commands] == [("kind", ["get", "clusters"])]


@pytest.mark.parametrize(
    "engine,image,expected",
    [
        ("docker", "mlflow-integration:integration", "mlflow-integration"),
        ("podman", "mlflow-integration:integration", "localhost/mlflow-integration"),
        ("podman", "localhost:5000/team/mlflow:integration", "localhost:5000/team/mlflow"),
    ],
)
def test_image_and_kubeconfig_are_consistent(runner, engine, image, expected):
    result, commands = runner(CONTAINER_TOOL=engine, MLFLOW_TEST_IMAGE=image)
    assert result.returncode == 0, result.stderr
    build = next(arguments for name, arguments, _ in commands if name == engine)
    reference = build[build.index("-t") + 1]
    assert reference.startswith(f"{expected}:integration-")
    if engine == "podman":
        saved = next(
            arguments
            for name, arguments, _ in commands
            if name == "podman" and arguments[0] == "save"
        )
        assert saved[-1] == reference
        archive = saved[saved.index("--output") + 1]
        assert any(
            name == "kind" and arguments[:3] == ["load", "image-archive", archive]
            for name, arguments, _ in commands
        )
    else:
        assert any(
            name == "kind" and arguments[:3] == ["load", "docker-image", reference]
            for name, arguments, _ in commands
        )
    assert any(
        name == "helm" and f"image.repository={expected}" in arguments
        for name, arguments, _ in commands
    )
    configurations = {configuration for _, _, configuration in commands}
    assert len(configurations) == 1
    assert "original-config" not in next(iter(configurations))
    assert not Path(next(iter(configurations))).exists()
    assert commands[-1][1] == ["delete", "cluster", "--name", "runner-owned"]


def test_build_failure_cleans_owned_cluster_and_preserves_failure(runner):
    result, commands = runner(FAIL_COMMAND="docker")
    assert result.returncode == 17
    assert commands[-1][1] == ["delete", "cluster", "--name", "runner-owned"]
    assert not any(name == "uv" for name, _, _ in commands)
