# Upstream changes: pre-request auth scoping for collection endpoints

## Background

The MLflow auth plugins (both basic auth and K8s auth) currently use post-response filtering for collection endpoints: MLflow queries all data, returns it, then the auth layer filters out unauthorized items. This is inefficient — MLflow loads and serializes data the caller will never see.

The goal is to move filtering into the MLflow storage layer (pre-request scoping): the auth layer tells MLflow which resources the caller is authorized to see **before** the query runs, so MLflow only loads authorized data.

Core argument (applies to all auth plugins, not just K8s): if a user only has permission to 1 experiment out of 1000, MLflow shouldn't have to query all 1000 and filter out 999 just to honor a page_size=20 request.

Two types of upstream changes are needed:
1. **`name IN (...)` filter support** (Solution B) — extend the filter parser so auth can inject `filter_string="name IN ('a','b','c')"` for top-level resources
2. **Optional `experiment_ids` parameter** (Solution A, subset) — add an `experiment_ids` param to 3 endpoints that currently lack one, so auth can scope by parent experiment

## Upstream strategy (per PE review)

1. **Open a GitHub issue first**, framed as: "Improve basic auth to prefilter based on user's permissions rather than post response filtering". Emphasize performance/pagination benefits — this benefits all auth plugins, not just K8s auth.
2. **Implement API changes + refactor MLflow's basic auth plugin** to use pre-request scoping — the basic auth refactoring is a token of goodwill to the community, showing the changes benefit everyone.
3. **Matthew can get Databricks MLflow maintainers to review**, since this impacts their managed offering.
4. **Then follow the same approach in the K8s auth plugin** (Kubeflow/RHOAI).

---

## Part 1: `name IN (...)` filter support (Solution B endpoints)

### Problem

MLflow 的 filter parser 有一个 `validate_list_supported` 守门函数，按端点类型决定哪些字段能用 `IN`。目前需要改的几个端点都不允许 `name IN (...)`。

### 改动原理

filter parser 有两道门（都在 `mlflow/utils/search_utils.py`）：

1. **`VALID_SEARCH_ATTRIBUTE_KEYS`**（第一道门）— 字段名是否合法，所有操作符都过这道门
2. **`validate_list_supported`**（第二道门）— 该字段能否用 `IN`，只在解析器遇到括号列表时触发

调用路径在基类 `SearchUtils._get_value()`（~L458）：
```python
elif isinstance(token, Parenthesis):
    cls.validate_list_supported(key)    # ← 第二道门
    return cls._parse_run_ids(token)
```

基类默认只允许 `run_id` 用 IN（L421-427）。子类可以 override 放宽。

SQL store 层已有通用的 IN 处理逻辑，不需要额外改动。

### 需要改的类

### 1. SearchExperimentsUtils（L1053）

**现状**：`VALID_SEARCH_ATTRIBUTE_KEYS = {"name", "creation_time", "last_update_time"}`，没有 override `validate_list_supported`，继承基类只允许 `run_id`。

**改动**：加 override，允许 `name`。

```python
@classmethod
def validate_list_supported(cls, key: str) -> None:
    if key != "name":
        raise MlflowException(
            "Only the 'name' attribute supports IN comparisons for experiments, "
            f"got '{key}'.",
            error_code=INVALID_PARAMETER_VALUE,
        )
```

**SQL store 验证**：`SearchExperimentsUtils.parse_search_filter` 解析后，SQL store 的 `_get_orderby_clauses` / filter 应用逻辑对 `name` 字段走 `SqlExperiment.name` 列，`get_sql_comparison_func` 已经能处理 IN comparator。需要跟一遍 `sqlalchemy_store.py` 的 `search_experiments` 确认。

**受益端点**：`SearchExperiments`（`GET /api/2.0/mlflow/experiments/search`）

---

### 2. SearchMCPServerUtils（L2698）

**现状**：`VALID_SEARCH_ATTRIBUTE_KEYS = {"name", "display_name", "status", "has_access_endpoints", "created_at", "last_updated_at"}`，`validate_list_supported` 只允许 `status`。

**改动**：把 `name` 加入白名单。

```python
@classmethod
def validate_list_supported(cls, key: str) -> None:
    if key not in ("status", "name"):
        raise MlflowException(
            f"Only 'status' and 'name' support IN comparisons for MCP servers, got '{key}'.",
            error_code=INVALID_PARAMETER_VALUE,
        )
```

**SQL store 验证**：`_apply_mcp_server_filter`（sqlalchemy_mixin.py ~L1189）的 else 分支对 `name` 走 `getattr(SqlMCPServer, key)` → `SearchUtils.get_sql_comparison_func(comparator, dialect)(attr, value)`，已经能处理 IN。无需改动。

**受益端点**：`search_mcp_servers`（`GET /api/3.0/mlflow/mcp-servers`）

---

### 3. SearchMCPAccessEndpointUtils（L2735）

**现状**：`VALID_SEARCH_ATTRIBUTE_KEYS = {"status", "server_name", "transport_type", "created_at", "last_updated_at"}`，没有 override `validate_list_supported`，继承基类只允许 `run_id`。

**改动**：加 override，允许 `server_name`。

```python
@classmethod
def validate_list_supported(cls, key: str) -> None:
    if key != "server_name":
        raise MlflowException(
            "Only the 'server_name' attribute supports IN comparisons for "
            f"MCP access endpoints, got '{key}'.",
            error_code=INVALID_PARAMETER_VALUE,
        )
```

**SQL store 验证**：需要确认 `_apply_mcp_access_endpoint_filter` 的 `server_name` 处理路径能正确处理 IN comparator。

**受益端点**：`search_all_access_endpoints`（`GET /api/3.0/mlflow/mcp-servers/endpoints`）

---

### 4. SearchModelUtils（L1267）— SearchRegisteredModels

**现状**：`VALID_SEARCH_ATTRIBUTE_KEYS = {"name"}`——`name` 已经是合法字段。

**但 `name IN (...)` 被双重拦截**：

**拦截 1 — Parser 层**：`SearchModelUtils` override 了 `_get_value()`（L1406），没有走基类的 `validate_list_supported` 路径，而是硬编码了 `run_id` 检查：

```python
# search_utils.py L1419-1425
elif isinstance(token, Parenthesis):
    if key != "run_id":
        raise MlflowException(
            "Only the 'run_id' attribute supports comparison with a list of quoted "
            "string values.",
            ...
        )
    return cls._parse_run_ids(token)
```

注意：这和前面 3 个类不同。前面的类继承基类 `_get_value()`，走 `validate_list_supported` 守门——只需 override 守门函数。`SearchModelUtils` 直接 override 了 `_get_value()`，绕过了 `validate_list_supported`。

**改动方案 A**（最小改动）：在 `_get_value()` 的 `Parenthesis` 分支里把 `run_id` 改为 `run_id` or `name`：

```python
elif isinstance(token, Parenthesis):
    if key not in ("run_id", "name"):
        raise MlflowException(...)
    return cls._parse_run_ids(token)
```

**改动方案 B**（更一致）：重构 `_get_value()` 让它调用 `validate_list_supported`，和基类一致，然后 override `validate_list_supported` 允许 `name`。对上游来说可能更好卖，因为统一了所有子类的行为。

**拦截 2 — SQL Store 层**：`sqlalchemy_store.py` L603 的 `_get_attribute_filter` 对 `name` 字段硬编码了 comparator 白名单：

```python
# store/model_registry/sqlalchemy_store.py L603
if comparator not in ("=", "!=", "LIKE", "ILIKE"):
    raise MlflowException(
        f"Invalid comparator for attribute: {comparator}",
        ...
    )
```

**改动**：加 `"IN"` 到白名单，并处理 IN 的 SQL 逻辑（`attr.in_(value)`）：

```python
if comparator not in ("=", "!=", "LIKE", "ILIKE", "IN"):
    raise MlflowException(...)
# 然后在生成 SQL 时处理 IN，get_sql_comparison_func 已有 IN 支持
```

⚠️ 这是和前面 3 个类的关键区别：SearchExperiments 和 MCP servers 的 SQL store 已经能处理 IN（通用路径），但 `model_registry/sqlalchemy_store.py` 有独立的 filter 处理逻辑，需要单独改。

**受益端点**：`SearchRegisteredModels`（`GET /api/2.0/mlflow/registered-models/search`）

---

### 5. SearchModelVersionUtils（L1452）— model-versions/search

**现状**：`VALID_SEARCH_ATTRIBUTE_KEYS = {"name", "version_number", "run_id", "source_path"}`——`name` 已经是合法字段。`VALID_STRING_ATTRIBUTE_COMPARATORS` 包含 `"IN"`。

**但 `name IN (...)` 仍被双重拦截**：

**拦截 1 — Parser 层**：和 `SearchModelUtils` 完全一样，`_get_value()`（L1597）override 了基类，硬编码 `run_id`：

```python
# search_utils.py L1610-1617
elif isinstance(token, Parenthesis):
    if key != "run_id":
        raise MlflowException(
            "Only the 'run_id' attribute supports comparison with a list of quoted "
            "string values.",
            ...
        )
    return cls._parse_run_ids(token)
```

**改动**：和 SearchModelUtils 一起改，`key not in ("run_id", "name")`。

**拦截 2 — SQL Store 层**：`model_registry/sqlalchemy_store.py` L688-695 同样限制了 IN 只能用于 `run_id`：

```python
# sqlalchemy_store.py L688-695
elif (
    comparator not in SearchModelVersionUtils.VALID_STRING_ATTRIBUTE_COMPARATORS
    or (comparator == "IN" and key != "run_id")   # ← 只允许 run_id
):
    raise MlflowException(...)
```

**改动**：把 `key != "run_id"` 改为 `key not in ("run_id", "name")`。

⚠️ **和 SearchRegisteredModels 的区别**：SQL store 的 IN 执行逻辑 **已经存在**（L703-708 的 `attr.in_(value)`），只需放宽守门条件。SearchRegisteredModels 则需要在 SQL store 里新增 IN comparator 白名单 + 执行逻辑。

**语义说明**：model version 的 `name` 字段 = 所属 registered model 的名字（父资源）。`name IN ('model-a', 'model-b')` 返回这些模型下的所有版本——正好是 auth 插件需要的粒度（SSRR 返回的是 registeredmodels 层级的权限名字）。

**受益端点**：`model-versions/search`（`GET /api/2.0/mlflow/model-versions/search`）

---

## 已确认：GraphQL mlflowSearchModelVersions 也受益

| 端点 | 搜索类 | 当前 IN 支持 | 是否需要加 name IN | 结论 |
|---|---|---|---|---|
| GraphQL mlflowSearchModelVersions | SearchModelVersionUtils | ❌ `name IN` 被阻止 | ✅ 需要 | **已确认可行（路径 B）**：GraphQL input `MlflowSearchModelVersionsInput` 有 `filter` 字段（`graphene.String()`），resolver 传给 `search_model_versions_impl` → 走同一个 `SearchModelVersionUtils` parser。上游 PR 放宽 `name IN` 后，auth 插件在 GraphQL middleware 注入 `filter` arg 即可。 |

---

## Part 2: Optional `experiment_ids` parameter (Solution A endpoints needing upstream changes)

Three endpoints currently lack an `experiment_ids` parameter but have internal support for experiment-scoped queries. Adding an optional `experiment_ids` param lets the auth layer inject the authorized set and filter at the storage layer.

### 1. BatchGetTraces / BatchGetTraceInfos

**现状**：API 只接受 `trace_ids`，无 `experiment_ids` 参数。

**内部支撑**：`trace_info` 已有 `experiment_id` 字段（数据库列已存在）。

**改动**：
- API 层：加 optional `experiment_ids` 参数
- Store 层：查询时加 `WHERE experiment_id IN (...)` 条件

**收益**：不仅是 auth scoping — 还避免加载无权 trace 的 span payload（可能很大），减少 DB I/O 和内存。

### 2. ListScorers

**现状**：API 只有单个 optional `experiment_id`，不传时查所有 workspace experiments 再过滤。

**内部支撑**：`list_scorers_across_experiments(experiment_ids)` 已经存在且接受 ID 列表。

**改动**：
- API 层：加 optional `experiment_ids`（复数）参数
- 内部调用从查所有 experiments 改为传入 authorized IDs → 直接调用 `list_scorers_across_experiments(experiment_ids)`

**收益**：跳过"查所有 workspace experiments + 逐个获取 scorers + 后置过滤"的路径。

---

## 改动总量估计（合并）

**Part 1 — filter parser（`mlflow/utils/search_utils.py`）**：
- SearchExperimentsUtils — override `validate_list_supported`，~5 行
- SearchMCPServerUtils — 扩展 `validate_list_supported`，~2 行
- SearchMCPAccessEndpointUtils — 加 override `validate_list_supported`，~5 行
- SearchModelUtils — 改 `_get_value()` 的 Parenthesis 分支，~2 行
- SearchModelVersionUtils — 改 `_get_value()` 的 Parenthesis 分支，~2 行

**Part 1 — SQL store（`mlflow/store/model_registry/sqlalchemy_store.py`）**：
- SearchRegisteredModels 的 filter 处理（L603）：加 `"IN"` 到白名单 + `attr.in_(value)` 逻辑，~5 行
- SearchModelVersions 的 filter 处理（L690）：放宽 `key != "run_id"` 为 `key not in ("run_id", "name")`，~1 行

**Part 2 — API + store changes**：
- BatchGetTraces / BatchGetTraceInfos：API proto + store 层加 `experiment_ids` 过滤，待调研具体行数
- ListScorers：API proto + 路由到 `list_scorers_across_experiments(experiment_ids)`，待调研具体行数

**Basic auth plugin refactoring**：
- 改造 basic auth 的 collection filter 逻辑使用新的 pre-request scoping 机制，作为对社区的 goodwill，待调研具体行数
