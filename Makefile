SHELL = /usr/bin/env bash -o pipefail
.SHELLFLAGS = -ec

IMG ?= mlflow-integration
UV_RUN ?= uv run
CONTAINER_TOOL ?= docker
IMAGE_PLATFORM ?=
MLFLOW_VERSION ?= $(shell sed -n 's/^ARG MLFLOW_VERSION=//p' Dockerfile)
CONTROLLER_TOOLS_VERSION ?= v0.19.0
CONTROLLER_GEN = go run sigs.k8s.io/controller-tools/cmd/controller-gen@$(CONTROLLER_TOOLS_VERSION)
GENERATED_FILES = api/mlflowconfig/v1/zz_generated.deepcopy.go config/crd/bases/mlflow.kubeflow.org_mlflowconfigs.yaml

.PHONY: install-dev
install-dev: ## Install uv dependencies for local development.
	@uv sync --extra dev

.PHONY: python-lint
python-lint: ## Run Python lint checks.
	@$(UV_RUN) ruff check .

.PHONY: python-typecheck
python-typecheck: ## Run Python type checker.
	@$(UV_RUN) ty check mlflow_kubernetes_plugins

.PHONY: python-test
python-test: ## Run Python test suite.
	@$(UV_RUN) pytest -v

.PHONY: python-build
python-build: ## Build Python distribution artifacts.
	@uv build

.PHONY: image-build
image-build: ## Build the container image.
	$(CONTAINER_TOOL) build -t $(IMG) .

.PHONY: image-verify
image-verify: ## Verify installed versions and auth startup in an existing image, offline.
	tar -cf - pyproject.toml hack/verify-image.py | \
		$(CONTAINER_TOOL) run --rm -i --network none \
		$(if $(IMAGE_PLATFORM),--platform $(IMAGE_PLATFORM)) --entrypoint sh "$(IMG)" \
		-c 'cd /tmp && tar --no-same-owner -xf - && python -I hack/verify-image.py pyproject.toml "$(MLFLOW_VERSION)"'

.PHONY: generate-deepcopy
generate-deepcopy: ## Generate deepcopy implementations for Go API types.
	$(CONTROLLER_GEN) object:headerFile="hack/boilerplate.go.txt" paths="./api/..."

.PHONY: generate-crd
generate-crd: ## Generate the MLflowConfig CRD manifest.
	$(CONTROLLER_GEN) crd paths="./api/..." output:crd:artifacts:config=config/crd/bases

.PHONY: generate-k8s
generate-k8s: generate-deepcopy generate-crd ## Generate all Kubernetes API artifacts.

.PHONY: verify-generated
verify-generated: generate-k8s ## Fail if generated Kubernetes API artifacts are stale.
	@status="$$(git status --porcelain=v1 --untracked-files=all -- $(GENERATED_FILES))"; \
	if [[ -n "$$status" ]]; then \
		echo "Generated Kubernetes API artifacts are stale. Run 'make generate-k8s' and commit the results."; \
		echo "$$status"; \
		git diff -- $(GENERATED_FILES) || true; \
		exit 1; \
	fi
