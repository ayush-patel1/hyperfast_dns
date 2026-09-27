from app.core.types import DataType
from app.detection.classifier import classify_schema_diff, primary_finding
from app.detection.events import FailureCategory, FailureType, Finding, Severity
from app.detection.profiling import profile_column
from app.detection.schema_diff import compare_schemas
from app.registry.models import Schema


def test_type_change_is_annotated_with_value_evidence():
    diff = compare_schemas(Schema.of({"customer_id": "INTEGER"}), Schema.of({"customer_id": "STRING"}))
    profiles = {"customer_id": profile_column("customer_id", ["1001", "1002", "ABC"])}
    [finding] = classify_schema_diff(diff, profiles)
    assert finding.failure_type == FailureType.TYPE_CHANGE
    assert finding.blocking and finding.severity == Severity.HIGH
    assert "67% of values are integer-like" in finding.detail and "ABC" in finding.detail


def test_timestamp_to_string_reports_detected_format():
    diff = compare_schemas(Schema.of({"created_at": "TIMESTAMP"}), Schema.of({"created_at": "STRING"}))
    profiles = {"created_at": profile_column("created_at", ["27/09/2026", "28/09/2026"])}
    [finding] = classify_schema_diff(diff, profiles)
    assert "'%d/%m/%Y'" in finding.detail


def _f(category, blocking, severity, ftype=FailureType.TYPE_CHANGE):
    return Finding(category=category, failure_type=ftype, severity=severity, blocking=blocking, detail="")


def test_primary_finding_prefers_blocking_then_category_then_severity():
    warn = _f(FailureCategory.SCHEMA_DRIFT, False, Severity.CRITICAL)
    dq = _f(FailureCategory.DATA_QUALITY, True, Severity.CRITICAL)
    schema = _f(FailureCategory.SCHEMA_DRIFT, True, Severity.MEDIUM)
    assert primary_finding([warn, dq]) is dq
    assert primary_finding([warn, dq, schema]) is schema


def test_widening_is_classified_non_blocking():
    diff = compare_schemas(Schema.of({"x": "INTEGER"}), Schema.of({"x": "FLOAT"}))
    [finding] = classify_schema_diff(diff, {})
    assert not finding.blocking
    assert finding.column == "x" and diff.changes[0].after == DataType.FLOAT
