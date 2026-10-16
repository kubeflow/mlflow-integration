# Kubernetes RBAC

Both plugins talk to the Kubernetes API, but they need different permissions depending on whether they are acting as the MLflow server or as the authenticated caller.

## MLflow Server Permissions

The workspace provider needs to list and watch namespaces. If you use the optional `MLflowConfig` CRD for artifact overrides, the server also needs access to that CRD and to list/watch the shared `mlflow-artifact-connection` secret across namespaces.

The provider watches only that secret name by using a `metadata.name=mlflow-artifact-connection` field selector. On Kubernetes 1.27+ the apiserver passes that field selector through authorization, so the RBAC rule can stay scoped with `resourceNames: ["mlflow-artifact-connection"]`.

Reusable example:

- [`examples/mlflow-server-rbac.yaml`](../examples/mlflow-server-rbac.yaml)

## Caller Permissions

The authorization plugin checks access against resources in the `mlflow.kubeflow.org` API group.

| Resource | Common verbs |
| --- | --- |
| `assistants` | `get`, `create`, `update` |
| `datasets` | `get`, `list`, `create`, `update`, `delete` |
| `experiments` | `get`, `list`, `create`, `update`, `delete` |
| `mcpservers` | `get`, `list`, `create`, `update`, `delete` |
| `skills` | `get`, `list`, `create`, `update`, `delete` |
| `registeredmodels` | `get`, `list`, `create`, `update`, `delete` |
| `gatewaysecrets` | `get`, `list`, `create`, `update`, `delete` |
| `gatewaysecrets/use` | `create` |
| `gatewayendpoints` | `get`, `list`, `create`, `update`, `delete` |
| `gatewayendpoints/use` | `create` |
| `gatewayguardrails` | `get`, `list`, `create`, `update`, `delete` |
| `gatewaybudgets` | `get`, `list`, `create`, `update`, `delete` |
| `gatewaymodeldefinitions` | `get`, `list`, `create`, `update`, `delete` |
| `gatewaymodeldefinitions/use` | `create` |

Reusable example:

- [`examples/team-a-workspace.yaml`](../examples/team-a-workspace.yaml)

## Fine-Grained Resource Names

Caller RBAC can also use Kubernetes `resourceNames` for fine-grained MLflow access.

Important details:

- Kubernetes ignores `resourceNames` on `create` without subresource because the object does not yet exist. The plugin mirrors this: name-scoped RBAC applies to `get`, `update`, `delete`, `list`, and subresource verbs like `create` on `<resource>/use`, but not bare `create`.
- Use the MLflow resource name, not the MLflow ID
- For `datasets`, the `resourceName` is the dataset name
- For `experiments`, the `resourceName` is the experiment name
- For `mcpservers`, the `resourceName` is the MCP server name
- For `skills`, use the skill name or `@organization/name`
- For `registeredmodels`, the `resourceName` is the registered model name
- For `gatewaysecrets`, the `resourceName` is the gateway secret name
- For `gatewayendpoints`, the `resourceName` is the gateway endpoint name
- For `gatewaymodeldefinitions`, the `resourceName` is the gateway model definition name
- `gatewayguardrails` intentionally does not support `resourceNames`. MLflow guardrail names are
  not unique within a workspace, so name-scoped RBAC would be ambiguous and could accidentally
  authorize multiple guardrails that share the same display name.
- `gatewaybudgets` intentionally does not support `resourceNames`. MLflow exposes only opaque
  budget-policy IDs rather than a declarative unique name that can be pre-provisioned through
  GitOps-friendly RBAC, so budget authorization stays at the workspace level.
- `gatewaybudgets` also rejects `GLOBAL` target scope in this plugin. Budget policies must remain
  workspace-scoped to preserve workspace isolation.

This is most useful for single-object operations such as:

- reading a specific dataset, experiment, MCP server, registered model, or gateway resource
- creating or updating runs, traces, tags, scorers, and other experiment-scoped writes
- creating or updating model versions, webhooks, and many gateway resources by name
- reading artifacts or trace details that resolve back to one experiment

Collection searches first check broad `list` permission in the workspace. An
explicit `resourceNames: ["*"]` grant on `get` or `list` is a plugin-level
compatibility convention and also permits the original query; Kubernetes RBAC
does not interpret that name as a wildcard itself. Otherwise, the plugin
discovers concrete named `get` grants through Kubernetes
SelfSubjectRulesReview, validates each name with an access review, and narrows
the request before MLflow queries storage. The caller's own search filter is
combined with the authorization scope. If the installed MLflow version cannot
enforce that scope, the plugin denies the request before dispatch.

This applies to experiment, evaluation-dataset, trace, registered-model,
model-version, MCP server, and MCP access-endpoint searches; batch trace reads;
scorer listing; and GraphQL model-version search. REST and AJAX variants use the
same rules. Collection responses are not filtered or backfilled after the query.
Other collection endpoints that already narrow explicit request IDs retain their
request-side authorization behavior.

Use the example manifest below as a starting point for both broad workspace access and name-scoped experiment access:

- [`examples/team-a-workspace.yaml`](../examples/team-a-workspace.yaml)

Example: allow an agent to send traces only to the `exp-a` experiment in the `team-a` workspace:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: mlflow-trace-agent
  namespace: team-a
rules:
  - apiGroups: ["mlflow.kubeflow.org"]
    resources: ["experiments"]
    resourceNames: ["exp-a"]
    verbs: ["update"]
```

## Skill Registry Permissions

Skill versions, tags, and aliases use `update` on the parent `skills` resource; deleting
that parent uses `delete`. Skill searches require broad `list` permission; named `get` or
`list` grants do not authorize searches. Uploaded content requires `get` on its skill,
independently of experiment permissions. Direct artifact writes are denied; register a new
version to upload content.

Like MCP, version registration requires `update` on the target skill, even when registration
automatically creates the parent. A named `update` grant therefore permits registering both
the first and subsequent versions of that skill. Bulk registration requires broad `update`
on skills. Direct parent creation requires broad `create`.

## Trusted Proxy Mode

When `MLFLOW_K8S_AUTH_AUTHORIZATION_MODE=subject_access_review`, the MLflow server must also be allowed to create `subjectaccessreviews.authorization.k8s.io`.

That permission is included in [`examples/mlflow-server-rbac.yaml`](../examples/mlflow-server-rbac.yaml).

Named collection scopes are enabled by default in trusted-proxy mode. When a
caller lacks broad collection permission, MLflow impersonates the forwarded user
and groups only to create a `SelfSubjectRulesReview` (SSRR). SSRR supplies candidate
resource names; MLflow confirms each name with a SubjectAccessReview before
narrowing the collection request.

The server ClusterRole in the example manifest and
[Helm chart](../charts/mlflow/templates/rbac.yaml) includes:

```yaml
- apiGroups: ["authentication.k8s.io"]
  resources: ["users", "groups"]
  verbs: ["impersonate:user-info"]
- apiGroups: ["authorization.k8s.io"]
  resources: ["selfsubjectrulesreviews"]
  verbs: ["impersonate-on:user-info:create"]
```

This requires Kubernetes 1.35 with the `ConstrainedImpersonation` feature gate
enabled, or Kubernetes 1.36+, where it is enabled by default. See
[Kubernetes constrained impersonation](https://kubernetes.io/docs/reference/access-authn-authz/user-impersonation/#constrained-impersonation).
If the feature is disabled, unavailable, or denied by RBAC, requests requiring
named-scope discovery are denied before querying MLflow storage. Broadly
authorized collection requests continue to work without SSRR. Set
`MLFLOW_K8S_AUTH_SAR_COLLECTION_SCOPE_DISCOVERY_ENABLED=false` to explicitly
disable discovery in SAR mode.

Do not also grant traditional `impersonate` permission: Kubernetes can fall back
to it, allowing operations beyond SSRR. Administrators can restrict permitted
identities by splitting the `users` and `groups` identity rule into separate rules
and adding `resourceNames` containing the allowed usernames and group names to
each rule. Every forwarded group must be permitted.

These rules cover ordinary users. Forwarded `system:serviceaccount:` and
`system:node:` identities require separate constrained impersonation modes and
are not granted discovery by these rules. Their directly authorized operations
and broadly authorized collection requests continue to work.

The proxy must authenticate callers and strip client-supplied identity headers
before setting the forwarded user and groups.

## Token Creation

To create a service-account token for testing:

```bash
kubectl -n team-a create token mlflow-writer
kubectl -n team-a create token mlflow-experiments-reader
```

Then send the token with the workspace header:

```bash
curl \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-MLFLOW-WORKSPACE: team-a" \
  https://mlflow.example/api/2.0/mlflow/runs/search
```

Use plain HTTP only for local-only testing such as `localhost` or a `kubectl port-forward`.
