"""MLflow capabilities required by request-side authorization scoping."""

import pytest
from mlflow.protos.model_registry_pb2 import SearchModelVersions, SearchRegisteredModels
from mlflow.protos.service_pb2 import (
    BatchGetTraceInfos,
    BatchGetTraces,
    ListScorers,
    SearchEvaluationDatasets,
    SearchExperiments,
    SearchTraces,
)
from mlflow.store.tracking.sqlalchemy_store import (
    _get_search_datasets_filter_clauses,
    _get_search_experiments_filter_clauses,
)
from mlflow.utils.search_utils import SearchEvaluationDatasetsUtils, SearchExperimentsUtils


@pytest.mark.parametrize("message", [BatchGetTraces, BatchGetTraceInfos, ListScorers])
def test_collection_requests_support_experiment_ids(message):
    field = message.DESCRIPTOR.fields_by_name["experiment_ids"]
    assert field.type == field.TYPE_STRING
    assert list(message(experiment_ids=["1", "2"]).experiment_ids) == ["1", "2"]


@pytest.mark.parametrize(
    ("parser", "sql_clauses", "key", "values"),
    [
        (
            SearchExperimentsUtils,
            _get_search_experiments_filter_clauses,
            "experiment_id",
            ("1", "2"),
        ),
        (SearchEvaluationDatasetsUtils, _get_search_datasets_filter_clauses, "name", ("a", "b")),
    ],
)
def test_collection_scope_in_filter_supported_by_parser_and_sql(parser, sql_clauses, key, values):
    filter_string = f"{key} IN (" + ", ".join(repr(value) for value in values) + ")"
    parsed = parser.parse_search_filter(filter_string)
    assert parsed == [{"type": "attribute", "key": key, "comparator": "IN", "value": values}]
    attribute_filters, non_attribute_filters = sql_clauses(parsed, "sqlite")
    assert len(attribute_filters) == 1
    assert not non_attribute_filters


@pytest.mark.parametrize(
    "message",
    [
        SearchExperiments,
        SearchRegisteredModels,
        SearchModelVersions,
        SearchEvaluationDatasets,
        SearchTraces,
        BatchGetTraces,
        BatchGetTraceInfos,
        ListScorers,
    ],
)
def test_collection_protobuf_inputs_can_be_serialized_as_query_fields(message):
    assert all(field.message_type is None for field in message.DESCRIPTOR.fields)
