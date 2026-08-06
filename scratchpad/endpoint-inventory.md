# Collection Endpoint Inventory: Current Behavior & Proposed Changes

This document has two parts:
- **First half (Endpoint Inventory)**: keyed by search endpoint — lists current behavior and proposed solution for each.
- **Second half (Solution Classification)**: reverse index, keyed by solution — lists endpoints belonging to each solution.

---

## Endpoint Inventory

Column definitions:
- **Current behavior (without broad permission)** = what happens today when the caller lacks broad list/get
- **Proposed change** = what this ticket changes
- "Out of scope" = no changes needed for this ticket

### Experiment (top-level resource)

| Parent | Endpoint | Current policy | Current behavior (without broad permission) | Proposed change |
|---|---|---|---|---|
| - | **SearchExperiments** | response_filter_experiments | Pass through → MLflow returns all → per-item SSAR check → filter response | **Solution B** |

### Experiment sub-resources

| Parent | Endpoint | Current policy | Current behavior (without broad permission) | Proposed change |
|---|---|---|---|---|
| Experiment | **SearchRuns** | request_filter_experiment_ids | Caller passes experiment_ids → per-item SSAR narrows the array → narrowed request sent to MLflow | Filter mechanism unchanged; SSRR optimization applies (see cross-cutting optimization below) |
| Experiment | **SearchLoggedModels** | request_filter_experiment_ids | Same as above | Same as above |
| Experiment | **SearchDatasets** | request_filter_experiment_ids | Same as above | Same as above |
| Experiment | **CalculateTraceFilterCorrelation** | request_filter_experiment_ids | Same as above | Same as above |
| Experiment | **QueryTraceMetrics** | request_filter_experiment_ids | Same as above | Same as above |
| Experiment | **SearchTracesV3** | request_filter_trace_locations | Caller passes locations array → per-item SSAR narrows it → narrowed request sent to MLflow | Same as above |
| Experiment | **GetMetricHistoryBulkInterval** | request_filter_run_ids | Caller passes run_ids → per-item SSAR narrows the array → narrowed request sent to MLflow | Same as above |
| Experiment | **SearchPromptOptimizationJobs** | request_filter_experiment_id | Caller passes single experiment_id → SSAR check → allowed or 403 | Filter mechanism unchanged; single ID, no batching benefit |
| Experiment | **SearchIssues** (v3.11) | request_filter_experiment_id | Same as above | Same as above |
| Experiment | **SearchTraces** | response_filter_traces | Pass through → per-item SSAR check on experiment → filter response | **Solution A** — API has `experiment_ids` array parameter |
| Experiment | **BatchGetTraces** | response_filter_traces | Pass through → per-item SSAR check → filter response | Only has `trace_ids`, no experiment parameter, no pagination, no filter_string → **Solution C** |
| Experiment | **BatchGetTraceInfos** (v3.11) | response_filter_traces | Same as above | Same as above → **Solution C** |
| Experiment | **SearchEvaluationDatasets** | response_filter_dataset_summaries | Pass through → per-item SSAR check on experiment → filter response | **Solution A** — API has `experiment_ids` array parameter |
| Experiment | **ListScorers** (v3.13 hybrid) | response_filter_scorers (hybrid) | **With experiment_id**: SSAR checks that experiment → allowed or 403. **Without experiment_id**: pass through → per-item SSAR filter | No pagination (no page_token), single optional `experiment_id` → **Solution C** |

### RegisteredModel (top-level resource)

| Parent | Endpoint | Current policy | Current behavior (without broad permission) | Proposed change |
|---|---|---|---|---|
| - | **SearchRegisteredModels** | response_filter_registered_models | Pass through → per-item SSAR check → filter response | **Solution B** — requires parser + SQL store changes (2 locations) |
| RegisteredModel | **model-versions/search** | response_filter_model_versions | Pass through → per-item SSAR check on owning model → filter response | **Solution B** — parser: add Parenthesis branch in `_get_value`; SQL store: relax L690 guard (`attr.in_()` logic already exists) |
| RegisteredModel | **GetLatestVersions** | No policy, has resource_name_parsers | SSAR checks the requested model name → allowed or 403 | Out of scope — single-resource endpoint |
| RegisteredModel | **ListWebhooks** | broad_only | Has broad list → pass / no → 403 | Out of scope — by design |

### Dataset (top-level resource)

| Parent | Endpoint | Current policy | Current behavior (without broad permission) | Proposed change |
|---|---|---|---|---|
| - | **GetDatasetExperimentIds** | No policy, has resource_name_parsers | SSAR checks the requested dataset → allowed or 403 | Out of scope — single-resource endpoint |
| - | **GetDatasetRecords** | No policy, has resource_name_parsers | Same as above | Out of scope |

### MCP Server (top-level resource, v3.14)

| Parent | Endpoint | Current policy | Current behavior (without broad permission) | Proposed change |
|---|---|---|---|---|
| - | **MCP servers list** | response_filter_mcp_servers | Pass through → per-item SSAR check → filter response | **Solution B** |
| MCP Server | **MCP access endpoints list** | response_filter_mcp_access_endpoints | Pass through → per-item SSAR check on owning server → filter response | **Solution B** — inject `server_name IN (...)` |

### Gateway resources (all broad_only or denied)

| Parent | Endpoint | Current policy | Current behavior | Proposed change |
|---|---|---|---|---|
| - | ListGatewaySecretInfos | broad_only | Has broad list → pass / no → 403 | Out of scope |
| - | ListGatewayEndpoints | broad_only | Same as above | Out of scope |
| - | ListGatewayModelDefinitions | broad_only | Same as above | Out of scope |
| - | ListGatewayBudgetPolicies (v3.11) | broad_only | Same as above | Out of scope |
| - | ListGatewayGuardrails (v3.12) | No policy | Broad permission check only | Out of scope |
| - | ListGatewayBudgetWindows (v3.11) | deny=True | Denied outright | Out of scope |
| Gateway Endpoint | ListGatewayEndpointBindings | No policy, has resource_name_parsers | SSAR checks the specified endpoint → allowed or 403 | Out of scope |

### GraphQL

| Parent | Endpoint | Current policy | Current behavior (without broad permission) | Proposed change |
|---|---|---|---|---|
| Experiment | **mlflowSearchRuns** | graphql request_filter | Narrows experimentIds array in input | Filter mechanism unchanged; SSRR optimization applies |
| Experiment | **mlflowSearchDatasets** | graphql request_filter | Same as above | Same as above |
| RegisteredModel | **mlflowSearchModelVersions** | graphql response_filter | Pass through → per-item SSAR filter on model_versions | **Solution B** — GraphQL input has `filter` field, shares `search_model_versions_impl`; inject filter arg in GraphQL auth middleware after upstream PR lands |

---

## Cross-cutting optimization: SSRR replaces per-item SSAR

This is an auth-backend optimization independent of the filter mechanism (pre-request vs post-response). It applies to all code paths that call `is_allowed(resource_name)`.

**Current state**: each permission check calls `authorizer.is_allowed(resource_name)` → 1 SSAR (K8s `SelfSubjectAccessReview` API call). For a request or response containing N resources, this produces N K8s API calls (caching partially mitigates, but cold path is still O(N)).

**Optimization**: 1 SSRR (`SelfSubjectRulesReview`) call to batch-fetch all authorized resource names for the workspace. Subsequent permission checks become set lookups (O(1), zero K8s API calls).

```
Current (all paths):                     After SSRR optimization:

for item in items:                       allowed = SSRR("experiments", "get", ws)
  name = resolve(item)                   → {"exp-a", "exp-c", ...}    ← 1 K8s call
  SSAR(name)  ← 1 K8s call each
                                         for item in items:
                                           name = resolve(item)
                                           name in allowed  ← set lookup, 0 K8s calls
```

**Benefit by filter mechanism**:

| Filter mechanism | Endpoint count | SSRR benefit |
|---|---|---|
| request_filter (pre-request, array params) | 7 REST + 2 GraphQL | N SSAR → 1 SSRR (N = caller-supplied resource count) |
| request_filter (pre-request, single param) | 2 | Single ID, no batching benefit |
| response_filter (post-response) | 11 REST + 1 GraphQL | N SSAR → 1 SSRR (N = response resource count, typically larger) |
| broad_only / single-resource / denied | 14 | N/A |

**Constraint**: SSRR optimization only applies in SSAR mode (requires user token to call `SelfSubjectRulesReview`). SAR mode (admin-on-behalf) retains existing per-item `SubjectAccessReview` behavior.

---

## Solution classification

SSRR is a cross-cutting auth-backend optimization; the solutions below address the **filter mechanism** layer. All endpoints requiring changes fall into three solutions:

### Solution A: SSRR → inject scoping array parameter (pre-request rewrite)

The API already has a narrowable array parameter (e.g. `experiment_ids`). SSRR fetches allowed resource names → convert to IDs → inject into array → MLflow queries only authorized data. **Pagination cursors remain correct** — the ideal approach.

| Endpoint | Injected parameter |
|---|---|
| SearchTraces | `experiment_ids` |
| SearchEvaluationDatasets | `experiment_ids` |

### Solution B: SSRR → inject filter_string (pre-request rewrite, requires upstream PR)

The API has `filter_string`, but MLflow currently **does not support** `name IN (...)`. Requires an upstream PR to extend the filter parser (details in `scratchpad/upstream-filter-in-support.md`), then SSRR fetches allowed resource names → inject `name IN ('a','b','c')` → MLflow queries only authorized data.

Upstream changes have been fully investigated (~20 lines of code + tests), spanning `mlflow/utils/search_utils.py` + `mlflow/store/model_registry/sqlalchemy_store.py`.

| Endpoint | Injected filter | Upstream change | Status |
|---|---|---|---|
| SearchExperiments | `name IN (...)` | `SearchExperimentsUtils`: add `validate_list_supported` override | Confirmed feasible |
| SearchRegisteredModels | `name IN (...)` | `SearchModelUtils._get_value()`: Parenthesis branch + `model_registry/sqlalchemy_store.py` L603: add IN allowlist + `attr.in_()` logic | Confirmed feasible (2 locations) |
| model-versions/search | `name IN (...)` | `SearchModelVersionUtils._get_value()`: Parenthesis branch + `model_registry/sqlalchemy_store.py` L690: relax guard (`attr.in_()` logic already exists) | Confirmed feasible (less SQL store change) |
| GraphQL mlflowSearchModelVersions | `name IN (...)` | Shares upstream SearchModelVersionUtils change; auth plugin adds request filter injecting `filter` arg in GraphQL middleware | Confirmed feasible (GraphQL input has `filter` field) |
| MCP servers list (v3.14) | `name IN (...)` | `SearchMCPServerUtils.validate_list_supported`: add `name` | Confirmed feasible |
| MCP access endpoints (v3.14) | `server_name IN (...)` | `SearchMCPAccessEndpointUtils`: add `validate_list_supported` override | Confirmed feasible |

### Solution C: keep post-response filtering + SSRR batch optimization (non-paginated endpoints)

The API has **no pagination** (no `page_token`/`max_results`), so pagination cursor corruption is not a concern — post-response filtering is correct as-is. Optimization: replace **per-item SSAR** checks with **1 SSRR** call to batch-fetch the allowed resource name set (N K8s API calls → 1).

```
Current:                                After Solution C:

for item in response:                   allowed = SSRR("experiments", "get", ws)
  name = resolve(item.exp_id)           → {"exp-a", "exp-c", ...}    ← 1 K8s call
  SSAR(name)  ← 1 K8s call each
                                        for item in response:
                                          name = resolve(item.exp_id)
                                          name in allowed  ← set lookup, 0 K8s calls
```

| Endpoint | Why Solution C |
|---|---|
| BatchGetTraces | Only has `trace_ids`, no experiment parameter, no pagination |
| BatchGetTraceInfos (v3.11) | Same as above |
| ListScorers (v3.13 hybrid) | Single optional `experiment_id`, no pagination. With ID: already authorized by resource_name; without ID: this path applies |

> **Note**: Solutions A/B/C all depend on SSRR to fetch the authorized scope. See the cross-cutting optimization section above for applicability and constraints.

---

## Summary

| Category | Count | Filter mechanism change? | SSRR cross-cutting optimization? |
|---|---|---|---|
| **response_filter (this ticket's target)** | **11 + 1 GraphQL** | **Yes** | **Yes** |
| Solution A (inject scoping array param) | 2 (SearchTraces, SearchEvaluationDatasets) | Approach confirmed | 1 SSRR replaces per-item SSAR |
| Solution B (inject filter_string, upstream PR) | 5 REST + 1 GraphQL | Approach confirmed, upstream changes investigated (~20 lines) | Same |
| Solution C (keep post-response + SSRR batch) | 3 (BatchGetTraces, BatchGetTraceInfos, ListScorers) | Keep post-response filtering | Same |
| **request_filter (existing pre-request filtering)** | **9 REST + 2 GraphQL** | **No — mechanism already correct** | **Yes (array-param endpoints benefit; single-param endpoints have no batching benefit)** |
| broad_only | 7 | No — by design | No — no resource_name check involved |
| Single-resource + resource_name_parsers | 4 list endpoints | No — single-resource validation | No — single ID, no batching benefit |
| Other (denied / pure broad) | 3 | No | No |

---

## Appendix: version-sensitive note

ListScorers authorization behavior depends on the MLflow version:
- **MLflow < 3.13** (`rules_base.py:464`): only `resource_name_parsers`, **no `collection_policy`**. Missing experiment_id → **403**.
- **MLflow >= 3.13** (`rules_v3_13.py:29`): adds `collection_policy=COLLECTION_POLICY_RESPONSE_SCORERS` + `fallback_to_collection_policy_on_missing_resource_reference=True`, making it a hybrid rule. Missing experiment_id → **post-response filtering**.

This ticket targets MLflow >= 3.13.
