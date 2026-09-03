# Kubernetes integration tests

These tests validate the behavior owned by this repository against a live MLflow
server installed by the Helm chart. They are intentionally separate from unit
and chart-render tests.

The executable lane uses a fresh Kind cluster, two labeled namespaces, an
unlabeled namespace, explicit edit/view/unprivileged Kubernetes Roles, and
ServiceAccount tokens. The MLflow SDK is run from pods so both token projection
and in-cluster service discovery are exercised. Coverage includes workspace
discovery, health, tracking operations, metrics, parameters, tags, registered
models, artifact upload/download, view-role mutation denial, and denied access
for unprivileged and cross-workspace requests.

Run locally with:

```bash
make install-dev
make kind-e2e
```

`make python-test` does not create a cluster and remains the fast unit suite.
The runner writes JUnit output to `test-results/` and captures Kubernetes
resources, events, pod descriptions, and server logs when a test fails.

## Deployment modes

The direct-token lane is executable here because the chart and plugin own the
ServiceAccount authentication path. Deployments that put an authenticating
proxy or gateway in front of MLflow should invoke the same functional contract
through that real gateway in the deployment repository. Tests must not fabricate
trusted identity headers against the Service directly; that would bypass the
trust boundary and would not verify proxy authentication.
