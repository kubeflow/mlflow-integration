"""Check installed image versions and auth app initialization without a cluster."""

import os
import sys
import tomllib
from importlib.metadata import distribution, version
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    with Path(sys.argv[1]).open("rb") as metadata_file:
        expected_plugin = tomllib.load(metadata_file)["project"]["version"]
    for package, expected in (
        ("mlflow-kubernetes-plugins", expected_plugin),
        ("mlflow", sys.argv[2]),
    ):
        installed = version(package)
        if installed != expected:
            raise RuntimeError(f"{package}: expected {expected}, installed {installed}")
        print(f"{package}=={installed}", flush=True)

    # A dummy configuration allows the real auth factory to initialize. No API
    # requests are needed to compile and validate the endpoint authorization rules.
    with TemporaryDirectory() as directory:
        kubeconfig = Path(directory) / "kubeconfig"
        kubeconfig.write_text(
            "apiVersion: v1\n"
            "kind: Config\n"
            "clusters:\n"
            "- name: offline\n"
            "  cluster:\n"
            "    server: https://127.0.0.1:1\n"
            "contexts:\n"
            "- name: offline\n"
            "  context:\n"
            "    cluster: offline\n"
            "    user: offline\n"
            "current-context: offline\n"
            "users:\n"
            "- name: offline\n"
            "  user:\n"
            "    token: image-verification-placeholder\n"
        )
        os.environ["KUBECONFIG"] = str(kubeconfig)
        os.environ["MLFLOW_K8S_AUTH_AUTHORIZATION_MODE"] = "subject_access_review"
        entry_point = next(
            entry
            for entry in distribution("mlflow-kubernetes-plugins").entry_points
            if entry.group == "mlflow.app" and entry.name == "kubernetes-auth"
        )
        entry_point.load()()
    print("Kubernetes auth app initialized successfully", flush=True)


if __name__ == "__main__":
    main()
