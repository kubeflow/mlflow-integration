"""Authorization rule deltas for MLflow 3.18."""

from __future__ import annotations

from mlflow_kubernetes_plugins.auth.resource_names import RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME
from mlflow_kubernetes_plugins.auth.rules import _experiments_rule

V3_18_PATH_AUTHORIZATION_RULES = {
    # Recomputes and stores an experiment's issue-detection schedule state after the UI saves
    # the schedule tags. It writes to the experiment named by `experiment_id` in the body.
    ("/ajax-api/3.0/mlflow/issues/schedule/state", "POST"): _experiments_rule(
        "update", resource_name_parsers=(RESOURCE_NAME_PARSER_EXPERIMENT_ID_TO_NAME,)
    ),
}


def apply_v3_18_deltas(request_rules: dict, path_rules: dict) -> None:
    path_rules.update(V3_18_PATH_AUTHORIZATION_RULES)
