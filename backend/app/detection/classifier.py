"""Deterministic failure classification.

No LLM is involved here: detection must be reproducible and cheap, and the
agent downstream should reason over facts, not over another model's guess.
"""
from __future__ import annotations

from app.core.types import DataType
from app.detection.distribution import DriftReport
from app.detection.events import (
    SEVERITY_RANK,
    FailureCategory,
    FailureType,
    Finding,
    Severity,
)
from app.detection.profiling import ColumnProfile
from app.detection.quality import Violation, ViolationType
from app.detection.schema_diff import ChangeKind, SchemaChange, SchemaDiff

_SCHEMA_SEVERITY = {
    ChangeKind.COLUMN_REMOVED: Severity.CRITICAL,
    ChangeKind.COLUMN_RENAMED: Severity.HIGH,
    ChangeKind.TYPE_CHANGE: Severity.HIGH,
    ChangeKind.NULLABILITY_CHANGE: Severity.MEDIUM,
    ChangeKind.CONSTRAINT_CHANGE: Severity.MEDIUM,
    ChangeKind.COLUMN_ADDED: Severity.LOW,
}

_DQ_SEVERITY = {
    ViolationType.MISSING_COLUMN: Severity.CRITICAL,
    ViolationType.TYPE_MISMATCH: Severity.HIGH,
    ViolationType.DUPLICATES: Severity.HIGH,
    ViolationType.REFERENTIAL_INTEGRITY: Severity.HIGH,
    ViolationType.UNEXPECTED_NULLS: Severity.MEDIUM,
    ViolationType.INVALID_FORMAT: Severity.MEDIUM,
    ViolationType.INVALID_ENUM: Severity.MEDIUM,
    ViolationType.OUT_OF_RANGE: Severity.MEDIUM,
    ViolationType.OUTLIERS: Severity.LOW,
}

_CATEGORY_PRIORITY = {
    FailureCategory.PIPELINE_FAILURE: 3,
    FailureCategory.SCHEMA_DRIFT: 2,
    FailureCategory.DATA_QUALITY: 1,
    FailureCategory.SEMANTIC_DRIFT: 0,
}


def _annotate_type_change(change: SchemaChange, profile: ColumnProfile | None) -> str:
    """Attach value-level evidence so the diagnosis starts from facts about the data."""
    if profile is None or change.after != DataType.STRING:
        return change.detail
    if change.before == DataType.INTEGER:
        return (f"{change.detail}; {profile.integer_like_ratio:.0%} of values are integer-like"
                + (f", non-numeric examples: {profile.non_numeric_examples}" if profile.non_numeric_examples else ""))
    if change.before in (DataType.TIMESTAMP, DataType.DATE):
        fmt = profile.best_datetime_format
        ratio = profile.datetime_format_ratios.get(fmt, 0) if fmt else 0
        return f"{change.detail}; best matching datetime format {fmt!r} parses {ratio:.0%} of values"
    return change.detail


def classify_schema_diff(diff: SchemaDiff, profiles: dict[str, ColumnProfile]) -> list[Finding]:
    return [
        Finding(
            category=FailureCategory.SCHEMA_DRIFT,
            failure_type=FailureType(c.kind.value),
            severity=_SCHEMA_SEVERITY[c.kind],
            blocking=c.breaking,
            column=c.column,
            detail=_annotate_type_change(c, profiles.get(c.column)) if c.kind == ChangeKind.TYPE_CHANGE else c.detail,
        )
        for c in diff.changes
    ]


def classify_violations(violations: list[Violation]) -> list[Finding]:
    return [
        Finding(
            category=FailureCategory.DATA_QUALITY,
            failure_type=FailureType(v.type.value),
            severity=_DQ_SEVERITY[v.type],
            blocking=v.type != ViolationType.OUTLIERS,
            column=v.column,
            detail=v.detail,
        )
        for v in violations
    ]


def classify_drift(reports: list[DriftReport], block: bool) -> list[Finding]:
    return [
        Finding(
            category=FailureCategory.SEMANTIC_DRIFT,
            failure_type=FailureType.DISTRIBUTION_DRIFT,
            severity=Severity.HIGH,
            blocking=block,
            column=r.column,
            detail=(f"'{r.column}' distribution shifted (mean {r.baseline_mean:.2f} -> {r.current_mean:.2f}): "
                    + "; ".join(r.signals)),
        )
        for r in reports if r.drifted
    ]


def primary_finding(findings: list[Finding]) -> Finding:
    """The finding that names the incident: blocking first, then category priority, then severity."""
    return max(findings, key=lambda f: (f.blocking, _CATEGORY_PRIORITY[f.category], SEVERITY_RANK[f.severity]))


def summarize(findings: list[Finding]) -> str:
    primary = primary_finding(findings)
    others = len(findings) - 1
    return primary.detail + (f" (+{others} related finding{'s' if others > 1 else ''})" if others else "")
