from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.detection.distribution import DriftReport
from app.detection.profiling import ColumnProfile
from app.detection.quality import Violation
from app.detection.schema_diff import SchemaDiff


class FailureCategory(StrEnum):
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    DATA_QUALITY = "DATA_QUALITY"
    PIPELINE_FAILURE = "PIPELINE_FAILURE"
    SEMANTIC_DRIFT = "SEMANTIC_DRIFT"


class FailureType(StrEnum):
    # schema drift
    TYPE_CHANGE = "TYPE_CHANGE"
    COLUMN_ADDED = "COLUMN_ADDED"
    COLUMN_REMOVED = "COLUMN_REMOVED"
    COLUMN_RENAMED = "COLUMN_RENAMED"
    NULLABILITY_CHANGE = "NULLABILITY_CHANGE"
    CONSTRAINT_CHANGE = "CONSTRAINT_CHANGE"
    # data quality
    TYPE_MISMATCH = "TYPE_MISMATCH"
    MISSING_COLUMN = "MISSING_COLUMN"
    UNEXPECTED_NULLS = "UNEXPECTED_NULLS"
    DUPLICATES = "DUPLICATES"
    INVALID_FORMAT = "INVALID_FORMAT"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    OUTLIERS = "OUTLIERS"
    INVALID_ENUM = "INVALID_ENUM"
    REFERENTIAL_INTEGRITY = "REFERENTIAL_INTEGRITY"
    # pipeline
    TRANSFORMATION_EXCEPTION = "TRANSFORMATION_EXCEPTION"
    SQL_FAILURE = "SQL_FAILURE"
    API_SCHEMA_FAILURE = "API_SCHEMA_FAILURE"
    MISSING_PARTITION = "MISSING_PARTITION"
    MALFORMED_JSON = "MALFORMED_JSON"
    # semantic
    DISTRIBUTION_DRIFT = "DISTRIBUTION_DRIFT"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


class Finding(BaseModel):
    category: FailureCategory
    failure_type: FailureType
    severity: Severity
    blocking: bool
    column: str | None = None
    detail: str


class FailureEvent(BaseModel):
    """Structured, self-contained description of one failed (or degraded) pipeline run.

    This is the payload published to the failure topic and the starting state of
    an investigation, so it carries everything needed without re-querying the run.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    pipeline_id: str
    run_id: str
    partition_id: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: FailureCategory
    failure_type: FailureType
    severity: Severity
    blocking: bool
    summary: str
    affected_columns: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    schema_diff: SchemaDiff | None = None
    expected_schema_version: int | None = None
    observed_schema_version: int | None = None
    violations: list[Violation] = Field(default_factory=list)
    drift_reports: list[DriftReport] = Field(default_factory=list)
    column_profiles: dict[str, ColumnProfile] = Field(default_factory=dict)
    sample_records: list[dict[str, Any]] = Field(default_factory=list)
    affected_records: int = 0
    error_message: str | None = None

    @property
    def fingerprint(self) -> str:
        """Stable across runs for the same underlying problem; used to de-duplicate incidents."""
        key = "|".join([
            self.tenant_id, self.pipeline_id, self.failure_type,
            ",".join(sorted(self.affected_columns)),
            self.schema_diff.to_fingerprint if self.schema_diff else "",
        ])
        return hashlib.sha256(key.encode()).hexdigest()[:20]
