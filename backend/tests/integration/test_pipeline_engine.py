import json

import pytest

from app.detection.events import FailureCategory, FailureType
from app.pipeline.engine import RunStatus
from app.pipeline.simulator import Scenario
from app.pipeline.sources import parse_envelope
from app.pipeline.storage import failed_partition_key
from app.registry.models import SchemaStatus

HEALTHY_PARTITIONS = ["2026-09-20", "2026-09-21"]


@pytest.fixture
def warmed(engine, definition, contract, source):
    """Two healthy partitions: bootstraps the registry and the drift baseline."""
    for p in HEALTHY_PARTITIONS:
        assert engine.run(definition, contract, source, p).status == RunStatus.SUCCEEDED
    return engine


def test_healthy_run_loads_partition_and_bootstraps_registry(engine, definition, contract, source):
    result = engine.run(definition, contract, source, "2026-09-20")
    assert result.status == RunStatus.SUCCEEDED
    assert result.rows_in == result.rows_loaded == 300
    assert result.failure_event is None
    assert engine.registry.latest_accepted("acme", "customer_pipeline").version == 1
    assert engine.warehouse.partition_count("acme", "customers", "2026-09-20") == 300
    assert [e.stage for e in result.logs][:2] == ["start", "extract"]


def test_reloading_a_partition_is_idempotent(warmed, definition, contract, source):
    warmed.run(definition, contract, source, "2026-09-20")
    assert warmed.warehouse.partition_count("acme", "customers", "2026-09-20") == 300


@pytest.mark.parametrize(
    ("scenario", "status", "category", "failure_type"),
    [
        (Scenario.TYPE_DRIFT, RunStatus.FAILED, FailureCategory.SCHEMA_DRIFT, FailureType.TYPE_CHANGE),
        (Scenario.DATE_FORMAT_DRIFT, RunStatus.FAILED, FailureCategory.SCHEMA_DRIFT, FailureType.TYPE_CHANGE),
        (Scenario.INVALID_VALUES, RunStatus.FAILED, FailureCategory.SCHEMA_DRIFT, FailureType.TYPE_CHANGE),
        (Scenario.NEW_COLUMN, RunStatus.SUCCEEDED_WITH_WARNINGS, FailureCategory.SCHEMA_DRIFT, FailureType.COLUMN_ADDED),
        (Scenario.SEMANTIC_DRIFT, RunStatus.FAILED, FailureCategory.SEMANTIC_DRIFT, FailureType.DISTRIBUTION_DRIFT),
        (Scenario.COLUMN_RENAME, RunStatus.FAILED, FailureCategory.SCHEMA_DRIFT, FailureType.COLUMN_RENAMED),
        (Scenario.COLUMN_REMOVED, RunStatus.FAILED, FailureCategory.SCHEMA_DRIFT, FailureType.COLUMN_REMOVED),
        (Scenario.NULLABILITY_CHANGE, RunStatus.FAILED, FailureCategory.SCHEMA_DRIFT, FailureType.NULLABILITY_CHANGE),
        (Scenario.DUPLICATES, RunStatus.FAILED, FailureCategory.DATA_QUALITY, FailureType.DUPLICATES),
        (Scenario.MALFORMED_JSON, RunStatus.FAILED, FailureCategory.PIPELINE_FAILURE, FailureType.MALFORMED_JSON),
        (Scenario.MISSING_PARTITION, RunStatus.FAILED, FailureCategory.PIPELINE_FAILURE, FailureType.MISSING_PARTITION),
    ],
)
def test_scenario_classification(warmed, definition, contract, source, scenario, status, category, failure_type):
    source.scenario = scenario
    result = warmed.run(definition, contract, source, "2026-09-27")
    event = result.failure_event
    assert result.status == status
    assert (event.category, event.failure_type) == (category, failure_type)
    assert event.blocking == (status == RunStatus.FAILED)
    if status == RunStatus.FAILED:
        assert warmed.warehouse.partition_count("acme", "customers", "2026-09-27") == 0


def test_type_drift_event_carries_evidence_for_diagnosis(warmed, definition, contract, source):
    source.scenario = Scenario.TYPE_DRIFT
    event = warmed.run(definition, contract, source, "2026-09-27").failure_event
    assert event.expected_schema_version == 1 and event.observed_schema_version == 2
    changed = {c.column: (c.before, c.after) for c in event.schema_diff.changes}
    assert changed == {"customer_id": ("INTEGER", "STRING"), "age": ("INTEGER", "STRING"),
                       "created_at": ("TIMESTAMP", "STRING")}
    assert event.column_profiles["customer_id"].integer_like_ratio == 1.0
    assert len(event.sample_records) == 20 and isinstance(event.sample_records[0]["customer_id"], str)
    assert event.affected_records == 300
    history = warmed.registry.history("acme", "customer_pipeline")
    assert [(v.version, v.status) for v in history] == [(1, SchemaStatus.ACCEPTED), (2, SchemaStatus.OBSERVED)]


def test_failed_partition_payload_is_stored_for_replay(warmed, definition, contract, source):
    source.scenario = Scenario.TYPE_DRIFT
    warmed.run(definition, contract, source, "2026-09-27")
    raw = warmed.object_store.get(failed_partition_key("acme", "customer_pipeline", "2026-09-27")).decode()
    assert len(json.loads(raw)["records"]) == 300


def test_replaying_stored_batch_after_upstream_recovers(warmed, definition, contract, source):
    source.scenario = Scenario.DUPLICATES
    warmed.run(definition, contract, source, "2026-09-27")
    source.scenario = Scenario.HEALTHY
    healthy = source.fetch("2026-09-27")
    batch = parse_envelope(healthy.source, "2026-09-27", healthy.raw_payload)
    result = warmed.run(definition, contract, source, "2026-09-27", batch=batch)
    assert result.status == RunStatus.SUCCEEDED and result.rows_loaded == 300


def test_semantic_drift_does_not_poison_baseline(warmed, definition, contract, source):
    before = warmed.baselines.load("acme", "customer_pipeline")["age"].count
    source.scenario = Scenario.SEMANTIC_DRIFT
    warmed.run(definition, contract, source, "2026-09-27")
    assert warmed.baselines.load("acme", "customer_pipeline")["age"].count == before


def test_transformation_exception_is_classified(warmed, definition, contract, source):
    broken = definition.model_copy(update={"transformations": {**definition.transformations,
                                                               "age": "CAST(name AS INTEGER)"}})
    event = warmed.run(broken, contract, source, "2026-09-27").failure_event
    assert event.failure_type == FailureType.TRANSFORMATION_EXCEPTION
    assert "Conversion" in event.error_message


def test_output_type_mismatch_against_contract(warmed, definition, contract, source):
    wrong = definition.model_copy(update={"transformations": {**definition.transformations,
                                                              "age": "CAST(age AS VARCHAR)"}})
    event = warmed.run(wrong, contract, source, "2026-09-27").failure_event
    assert event.category == FailureCategory.DATA_QUALITY
    assert event.failure_type == FailureType.TYPE_MISMATCH and event.affected_columns == ["age"]
