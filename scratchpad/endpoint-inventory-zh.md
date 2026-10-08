# 端点完整清单：按资源层级 + 当前行为 + 本次改造方式

本文档分两部分：
- **前半（端点清单）**：以 search endpoint 为 key，列出每个端点的当前行为和改造路径。
- **后半（改造路径分类）**：反向索引，以改造路径为 key，列出归属该路径的端点。

---

## 端点清单

表格说明：
- **当前行为（无 broad 权限时）** = 当前系统在用户没有 broad list/get 时的行为
- **本次改造** = ticket 要求怎么改
- "不在 scope" = 本次 ticket 不需要动

### Experiment（顶级资源）

| 父资源 | 端点 | 当前 policy | 当前行为（无 broad 权限时） | 本次改造 |
|---|---|---|---|---|
| - | **SearchExperiments** | response_filter_experiments | 放行 → MLflow 返回全部 → 逐个 SSAR 检查 get → 过滤 | **路径 B** — 上游 PR 让 filter 支持 `name IN (...)` 后可注入 |

### Experiment 的子资源

| 父资源 | 端点 | 当前 policy | 当前行为（无 broad 权限时） | 本次改造 |
|---|---|---|---|---|
| Experiment | **SearchRuns** | request_filter_experiment_ids | 用户传 experiment_ids → 逐个 SSAR 缩小数组 → 缩小后的请求发 MLflow | 过滤机制不变；SSRR 优化适用（见下方横切优化） |
| Experiment | **SearchLoggedModels** | request_filter_experiment_ids | 同上 | 同上 |
| Experiment | **SearchDatasets** | request_filter_experiment_ids | 同上 | 同上 |
| Experiment | **CalculateTraceFilterCorrelation** | request_filter_experiment_ids | 同上 | 同上 |
| Experiment | **QueryTraceMetrics** | request_filter_experiment_ids | 同上 | 同上 |
| Experiment | **SearchTracesV3** | request_filter_trace_locations | 用户传 locations 数组 → 逐个 SSAR 缩小 → 缩小后发 MLflow | 同上 |
| Experiment | **GetMetricHistoryBulkInterval** | request_filter_run_ids | 用户传 run_ids → 逐个 SSAR 缩小 → 缩小后发 MLflow | 同上 |
| Experiment | **SearchPromptOptimizationJobs** | request_filter_experiment_id | 用户传单个 experiment_id → SSAR 检查 → 有权放行 / 无权 403 | 过滤机制不变；单个 ID 无批量收益 |
| Experiment | **SearchIssues** (v3.11) | request_filter_experiment_id | 同上 | 同上 |
| Experiment | **SearchTraces** | response_filter_traces | 放行 → 后置逐个 SSAR 检查 experiment → 过滤 | **路径 A** — 可改造 experiment_ids 数组（API 有该参数） |
| Experiment | **BatchGetTraces** | response_filter_traces | 放行 → 后置逐个 SSAR 检查 → 过滤 | 当前无 `experiment_ids` 参数；`trace_info` 内部有 `experiment_id` → 上游新增可选 `experiment_ids` 参数 → **路径 A** |
| Experiment | **BatchGetTraceInfos** (v3.11) | response_filter_traces | 同上 | 同上 → **路径 A** |
| Experiment | **SearchEvaluationDatasets** | response_filter_dataset_summaries | 放行 → 后置逐个 SSAR 检查 experiment → 过滤 | **路径 A** — 可改造 experiment_ids 数组（API 有该参数） |
| Experiment | **ListScorers** (v3.13 hybrid) | response_filter_scorers (hybrid) | **有 experiment_id 时**：SSAR 检查该实验权限 → 有权放行 / 无权 403。**无 experiment_id 时**：放行 → 后置逐个 SSAR 过滤 | 内部 `list_scorers_across_experiments(experiment_ids)` 已接受 ID 列表；上游暴露可选 `experiment_ids` 参数 → **路径 A** |

### RegisteredModel（顶级资源）

| 父资源 | 端点 | 当前 policy | 当前行为（无 broad 权限时） | 本次改造 |
|---|---|---|---|---|
| - | **SearchRegisteredModels** | response_filter_registered_models | 放行 → 逐个 SSAR 检查 get → 过滤 | **路径 B** — 上游 PR 让 filter 支持 `name IN (...)` 后可注入（需改 parser + SQL store 两处） |
| RegisteredModel | **model-versions/search** | response_filter_model_versions | 放行 → 逐个 SSAR 检查所属 model 的 get → 过滤 | **路径 B** — 上游 PR 让 filter 支持 `name IN (...)` 后可注入（parser 改 `_get_value` 的 `run_id` 守门 + SQL store 放宽 L690 的 `key != "run_id"` 条件，`attr.in_()` 逻辑已存在） |
| RegisteredModel | **GetLatestVersions** | 无 policy，有 resource_name_parsers | SSAR 检查请求里指定的 model name → 有权放行 / 无权 403 | 不在 scope — 单资源端点 |
| RegisteredModel | **ListWebhooks** | broad_only | 有 broad list → 放行 / 没有 → 403 | 不在 scope — 设计如此 |

### Dataset（顶级资源）

| 父资源 | 端点 | 当前 policy | 当前行为（无 broad 权限时） | 本次改造 |
|---|---|---|---|---|
| - | **GetDatasetExperimentIds** | 无 policy，有 resource_name_parsers | SSAR 检查请求里的 dataset → 有权放行 / 无权 403 | 不在 scope — 单资源端点 |
| - | **GetDatasetRecords** | 无 policy，有 resource_name_parsers | 同上 | 不在 scope |

### MCP Server（顶级资源，v3.14）

| 父资源 | 端点 | 当前 policy | 当前行为（无 broad 权限时） | 本次改造 |
|---|---|---|---|---|
| - | **MCP servers list** | response_filter_mcp_servers | 放行 → 逐个 SSAR 检查 get → 过滤 | **路径 B** — 上游 PR 让 filter 支持 `name IN (...)` 后可注入 |
| MCP Server | **MCP access endpoints list** | response_filter_mcp_access_endpoints | 放行 → 逐个 SSAR 检查所属 server 的 get → 过滤 | **路径 B** — 上游 PR 让 filter 支持 `server_name IN (...)` 后可注入 |

### Gateway 资源（全部 broad_only 或 denied）

| 父资源 | 端点 | 当前 policy | 当前行为 | 本次改造 |
|---|---|---|---|---|
| - | ListGatewaySecretInfos | broad_only | broad list → 放行 / 没有 → 403 | 不在 scope |
| - | ListGatewayEndpoints | broad_only | 同上 | 不在 scope |
| - | ListGatewayModelDefinitions | broad_only | 同上 | 不在 scope |
| - | ListGatewayBudgetPolicies (v3.11) | broad_only | 同上 | 不在 scope |
| - | ListGatewayGuardrails (v3.12) | 无 policy | 只做 broad 权限检查 | 不在 scope |
| - | ListGatewayBudgetWindows (v3.11) | deny=True | 直接拒绝 | 不在 scope |
| Gateway Endpoint | ListGatewayEndpointBindings | 无 policy，有 resource_name_parsers | SSAR 检查指定 endpoint → 有权放行 / 无权 403 | 不在 scope |

### GraphQL

| 父资源 | 端点 | 当前 policy | 当前行为（无 broad 权限时） | 本次改造 |
|---|---|---|---|---|
| Experiment | **mlflowSearchRuns** | graphql request_filter | 缩小 input 里的 experimentIds 数组 | 过滤机制不变；SSRR 优化适用 |
| Experiment | **mlflowSearchDatasets** | graphql request_filter | 同上 | 同上 |
| RegisteredModel | **mlflowSearchModelVersions** | graphql response_filter | 放行 → 后置逐个 SSAR 过滤 model_versions | **路径 B** — GraphQL input 有 `filter` 字段，底层共用 `search_model_versions_impl`；上游 PR 支持 `name IN (...)` 后，在 GraphQL auth middleware 注入 filter arg |

---

## 横切优化：SSRR 替代逐个 SSAR

这是一个独立于过滤机制（前置/后置）的授权后端优化，适用于所有调用 `is_allowed(resource_name)` 的路径。

**现状**：每次权限检查调用 `authorizer.is_allowed(resource_name)` → 1 次 SSAR（K8s `SelfSubjectAccessReview` API 调用）。对于包含 N 个资源的请求或响应，产生 N 次 K8s API 调用（有缓存可部分缓解，但首次访问仍是 O(N)）。

**优化**：用 1 次 SSRR（`SelfSubjectRulesReview`）批量获取用户在该 workspace 下所有被授权的 resource name set，后续权限判定变为 set lookup（O(1)，零 K8s API 调用）。

```
现状（所有路径共用）：                    SSRR 优化后：

for item in items:                      allowed = SSRR("experiments", "get", ws)
  name = resolve(item)                  → {"exp-a", "exp-c", ...}    ← 1 次 K8s 调用
  SSAR(name)  ← 每个 1 次 K8s 调用
                                        for item in items:
                                          name = resolve(item)
                                          name in allowed  ← set lookup, 0 次 K8s 调用
```

**受益范围**：

| 过滤机制 | 端点数 | SSRR 收益 |
|---|---|---|
| request_filter（前置，数组参数） | 7 REST + 2 GraphQL | N 次 SSAR → 1 次 SSRR（N = 用户传入的资源数） |
| request_filter（前置，单个参数） | 2 | 单个 ID，无批量收益 |
| response_filter（后置） | 11 REST + 1 GraphQL | N 次 SSAR → 1 次 SSRR（N = 响应中的资源数，通常更大） |
| broad_only / 单资源 / denied | 14 | 不适用 |

**约束**：SSRR 优化仅在 SSAR 模式下生效（有用户 token 才能调 `SelfSubjectRulesReview`）。SAR 模式（管理员代查）保持现有逐个 `SubjectAccessReview` 行为不变。

---

## 改造路径分类

SSRR 是授权后端的横切优化；下面的路径分类针对的是**过滤机制**层面的改造。

### 为什么不同端点用不同的注入方式

`experiment_ids` 和 `name IN (...)` 的选择是务实的，不是按类别划分的。每个端点用的是**改动量最小**的参数：

- SearchTraces、SearchEvaluationDatasets → API 已有 `experiment_ids` → 直接注入
- BatchGetTraces、ListScorers → 当前无对应参数，但底层 store 支持 `experiment_id` 过滤 → 上游新增可选 `experiment_ids`（经 PE review 反馈确认）
- model-versions/search → 是 RegisteredModel 的子资源，但其 `filter_string` 已支持 `name`，只缺 `IN` → 扩展 `filter_string` 而非新增参数
- SearchExperiments、SearchRegisteredModels → `filter_string` 已有 `name` 作为合法 key，只缺 `IN` 运算符 → 扩展 `filter_string`

因此资源层级（子资源 vs 顶级）与注入方式（`experiment_ids` vs `filter_string`）之间的对应关系并不整齐 — 但强行统一只会增加不必要的上游改动量。

所有需改造的端点归入两条路径：

### 路径 A：SSRR → 注入 scoping 数组参数（前置改写）

SSRR 拿到允许的 resource name → 转 ID → 注入 `experiment_ids` 数组 → MLflow 只查授权范围内的数据。**分页 cursor 正确**，是最理想的方案。

| 端点 | 注入的参数 | 需要上游改动？ |
|---|---|---|
| SearchTraces | `experiment_ids` | 否 — 参数已存在 |
| SearchEvaluationDatasets | `experiment_ids` | 否 — 参数已存在 |
| BatchGetTraces | `experiment_ids` | 是 — 新增可选参数；`trace_info` 内部已有 `experiment_id`，store 层加小量 `IN` 过滤 |
| BatchGetTraceInfos (v3.11) | `experiment_ids` | 是 — 同 BatchGetTraces |
| ListScorers (v3.13 hybrid) | `experiment_ids` | 是 — 内部 `list_scorers_across_experiments(experiment_ids)` 已存在；暴露为可选 API 参数 |

### 路径 B：SSRR → 注入 filter_string（前置改写，需上游 PR）

API 有 `filter_string`，但当前 MLflow **不支持** `name IN (...)`。需要先提上游 PR 扩展 filter parser（详见 `scratchpad/upstream-filter-in-support.md`），然后 SSRR 拿到允许的 resource name → 注入 `name IN ('a','b','c')` → MLflow 只查授权范围内的数据。

上游改动已调研完毕（~20 行代码 + 测试），涉及 `mlflow/utils/search_utils.py` + `mlflow/store/model_registry/sqlalchemy_store.py`。

| 端点 | 注入的 filter 字段 | 上游改动 | 状态 |
|---|---|---|---|
| SearchExperiments | `name IN (...)` | `SearchExperimentsUtils` 加 override `validate_list_supported` | ✅ 已确认可行 |
| SearchRegisteredModels | `name IN (...)` | `SearchModelUtils._get_value()` Parenthesis 分支 + `model_registry/sqlalchemy_store.py` L603 加 IN 白名单 + `attr.in_()` 逻辑 | ✅ 已确认可行（需改两处） |
| model-versions/search | `name IN (...)` | `SearchModelVersionUtils._get_value()` Parenthesis 分支 + `model_registry/sqlalchemy_store.py` L690 放宽守门条件（`attr.in_()` 逻辑已存在） | ✅ 已确认可行（SQL store 改动更少） |
| GraphQL mlflowSearchModelVersions | `name IN (...)` | 共用上游 SearchModelVersionUtils 改动；auth 插件需在 GraphQL middleware 增加 request filter 注入 `filter` arg | ✅ 已确认可行（GraphQL input 有 `filter` 字段） |
| MCP servers list (v3.14) | `name IN (...)` | `SearchMCPServerUtils.validate_list_supported` 加 `name` | ✅ 已确认可行 |
| MCP access endpoints (v3.14) | `server_name IN (...)` | `SearchMCPAccessEndpointUtils` 加 override `validate_list_supported` | ✅ 已确认可行 |

> **注意**：路径 A/B 均依赖 SSRR 获取授权范围。SSRR 的适用条件和约束见上方"横切优化"章节。

---

## 汇总

| 分类 | 端点数 | 过滤机制改造？ | SSRR 横切优化？ |
|---|---|---|---|
| **response_filter（本次目标）** | **11 + 1 GraphQL** | **是** | **是** |
| 其中：路径 A（注入 `experiment_ids`） | 5（SearchTraces、SearchEvaluationDatasets、BatchGetTraces、BatchGetTraceInfos、ListScorers） | 2 个参数已存在；3 个需上游 API 改动 | 1 次 SSRR 替代逐个 SSAR |
| 其中：路径 B（注入 filter_string，需上游 PR） | 5 REST + 1 GraphQL | 方案明确，上游改动已调研（~20 行） | 同上 |
| **request_filter（已有前置过滤）** | **9 REST + 2 GraphQL** | **否 — 过滤机制已正确** | **是（数组参数端点受益，单参数端点无批量收益）** |
| broad_only | 7 | 否 — 设计如此 | 否 — 不涉及 resource_name 检查 |
| 单资源 + resource_name_parsers | 4 个 list 端点 | 否 — 单资源验证 | 否 — 单个 ID 无批量收益 |
| 其他（denied / 纯 broad） | 3 | 否 | 否 |

---

## 附录：版本敏感提醒

ListScorers 的授权行为取决于 MLflow 版本：
- **MLflow < 3.13**（`rules_base.py:464`）：只有 `resource_name_parsers`，**没有 `collection_policy`**。不传 experiment_id → **403**。
- **MLflow >= 3.13**（`rules_v3_13.py:29`）：加了 `collection_policy=COLLECTION_POLICY_RESPONSE_SCORERS` + `fallback_to_collection_policy_on_missing_resource_reference=True`，变成 hybrid rule。不传 experiment_id → **后置过滤**。

本次改造面向 MLflow >= 3.13。
