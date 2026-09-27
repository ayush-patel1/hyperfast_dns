from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import duckdb
from pydantic import BaseModel, Field

from app.contracts.model import DataContract, DriftAction
from app.core.logging import LogEntry, RunLogger
from app.detection import classifier
from app.detection.distribution import BaselineStore, DriftReport, compare_to_baseline, numeric_values
from app.detection.events import (
    FailureCategory,
    FailureEvent,
    FailureType,
    Finding,
    Severity,
)
from app.detection.profiling import ColumnProfile, profile_records
from app.detection.quality import Violation, ViolationType, validate_contract
from app.detection.schema_diff import SchemaDiff, compare_schemas
from app.pipeline.definition import PipelineDefinition
from app.pipeline.sources import (
    ApiSchemaError,
    MalformedPayload,
    PartitionNotFound,
    Source,
    SourceBatch,
    SourceError,
)
from app.pipeline.storage import ObjectStore, failed_partition_key
from app.pipeline.warehouse import Warehouse
from app.registry.models import SchemaStatus
from app.registry.service import SchemaRegistry

SAMPLE_RECORDS = 20


class RunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNINGS = "SUCCEEDED_WITH_WARNINGS"
    FAILED = "FAILED"


class RunResult(BaseModel):
    run_id: str
    tenant_id: str
    pipeline_id: str
    pipeline_version: int
    partition_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    rows_in: int = 0
    rows_loaded: int = 0
    schema_version: int | None = None
    failure_event: FailureEvent | None = None
    logs: list[LogEntry] = Field(default_factory=list)


class _RunContext:
    def __init__(self, definition: PipelineDefinition, partition_id: str) -> None:
        self.run_id = str(uuid.uuid4())
        self.definition = definition
        self.partition_id = partition_id
        self.started = datetime.now(UTC)
        self.t0 = time.perf_counter()
        self.log = RunLogger("pipeline", run_id=self.run_id, pipeline_id=definition.id,
                             tenant_id=definition.tenant_id, partition_id=partition_id)
        self.findings: list[Finding] = []
        self.batch: SourceBatch | None = None
        self.diff: SchemaDiff | None = None
        self.expected_version: int | None = None
        self.observed_version: int | None = None
        self.profiles: dict[str, ColumnProfile] = {}
        self.violations: list[Violation] = []
        self.drift_reports: list[DriftReport] = []
        self.error: str | None = None
        self.affected: set[int] = set()


class PipelineEngine:
    def __init__(
        self,
        registry: SchemaRegistry,
        warehouse: Warehouse,
        baselines: BaselineStore,
        object_store: ObjectStore,
    ) -> None:
        self.registry = registry
        self.warehouse = warehouse
        self.baselines = baselines
        self.object_store = object_store

    def run(
        self,
        definition: PipelineDefinition,
        contract: DataContract,
        source: Source,
        partition_id: str,
        batch: SourceBatch | None = None,
    ) -> RunResult:
        """Execute one partition. `batch` is supplied on replay so the stored
        failed payload is reprocessed instead of re-fetching from upstream."""
        ctx = _RunContext(definition, partition_id)
        ctx.log.info("start", f"run started (pipeline v{definition.version})")
        rows_loaded = 0
        try:
            ctx.batch = batch or source.fetch(partition_id)
            ctx.log.info("extract", f"extracted {len(ctx.batch.records)} records from {ctx.batch.source}",
                         schema_declared=ctx.batch.schema_declared)
            if self._check_schema(ctx) and (rows := self._process(ctx, contract)) is not None:
                rows_loaded = rows
        except SourceError as exc:
            self._source_failure(ctx, exc)
        return self._finish(ctx, rows_loaded)

    # --- stages ---

    def _check_schema(self, ctx: _RunContext) -> bool:
        d, batch = ctx.definition, ctx.batch
        assert batch is not None
        expected = self.registry.latest_accepted(d.tenant_id, d.id)
        if expected is None:
            expected = self.registry.record(d.tenant_id, d.id, batch.schema_, SchemaStatus.ACCEPTED,
                                            reason="bootstrapped from first observed partition")
            ctx.log.info("schema", f"bootstrapped schema registry at v{expected.version}")
        ctx.expected_version = expected.version

        if batch.schema_.fingerprint() == expected.fingerprint:
            ctx.observed_version = expected.version
            ctx.log.info("schema", f"source schema matches accepted v{expected.version}")
            return True

        observed = self.registry.record(d.tenant_id, d.id, batch.schema_, SchemaStatus.OBSERVED,
                                        reason=f"observed in partition {ctx.partition_id}")
        ctx.observed_version = observed.version
        ctx.profiles = profile_records(batch.records)
        expected_samples = {c: self.warehouse.column_values(d.tenant_id, d.target_table, c, limit=500)
                            for c in expected.schema_.fields if c not in batch.schema_.fields}
        observed_samples = {c: [r.get(c) for r in batch.records[:500]]
                            for c in batch.schema_.fields if c not in expected.schema_.fields}
        ctx.diff = compare_schemas(expected.schema_, batch.schema_, expected_samples, observed_samples)
        ctx.diff.from_version, ctx.diff.to_version = expected.version, observed.version
        ctx.findings += classifier.classify_schema_diff(ctx.diff, ctx.profiles)

        for change in ctx.diff.changes:
            log = ctx.log.error if change.breaking else ctx.log.warning
            log("schema", change.detail, change=change.kind, column=change.column)
        if ctx.diff.is_breaking:
            ctx.log.error("schema", f"schema contract violation: v{expected.version} -> v{observed.version} is breaking")
            return False
        return True

    def _process(self, ctx: _RunContext, contract: DataContract) -> int | None:
        d, batch = ctx.definition, ctx.batch
        assert batch is not None
        with self.warehouse.connect() as con:
            try:
                self.warehouse.stage(con, batch.schema_, batch.records)
            except duckdb.Error as exc:
                return self._pipeline_error(ctx, FailureType.SQL_FAILURE, "stage", exc)
            try:
                rows, out_types = self.warehouse.transform(con, d.transformations)
            except duckdb.Error as exc:
                return self._pipeline_error(ctx, FailureType.TRANSFORMATION_EXCEPTION, "transform", exc)
            ctx.log.info("transform", f"applied {len(d.transformations)} column transformations", rows=len(rows))

            ctx.violations = self._output_type_violations(out_types, contract, len(rows))
            ctx.violations += validate_contract(
                rows, contract,
                reference_lookup=lambda table, col: self.warehouse.distinct_values(d.tenant_id, table, col),
            )
            ctx.findings += classifier.classify_violations(ctx.violations)
            for v in ctx.violations:
                ctx.affected.update(v.row_indexes)
                ctx.log.error("validate", v.detail, violation=v.type, column=v.column, failing_rows=v.failing_rows)

            ctx.drift_reports = self._check_drift(ctx, contract, rows)
            ctx.findings += classifier.classify_drift(ctx.drift_reports, contract.drift.action == DriftAction.BLOCK)

            if any(f.blocking for f in ctx.findings):
                ctx.log.error("validate", "blocking findings present; partition not loaded")
                return None
            loaded = self.warehouse.load(con, d.tenant_id, d.target_table, contract.as_schema(),
                                         ctx.partition_id, ctx.run_id)
        ctx.log.info("load", f"loaded {loaded} rows into {d.tenant_id}.{d.target_table}")
        if not any(f.category == FailureCategory.SEMANTIC_DRIFT for f in ctx.findings):
            self.baselines.update(d.tenant_id, d.id, rows, contract.drift.columns)
        return loaded

    @staticmethod
    def _output_type_violations(out_types: dict, contract: DataContract, n: int) -> list[Violation]:
        return [
            Violation(type=ViolationType.TYPE_MISMATCH, column=col, failing_rows=n, total_rows=n,
                      detail=f"transformed '{col}' is {out_types[col]}, contract requires {field.type}")
            for col, field in contract.schema_.items()
            if col in out_types and out_types[col] != field.type
        ]

    def _check_drift(self, ctx: _RunContext, contract: DataContract, rows: list[dict[str, Any]]) -> list[DriftReport]:
        baselines = self.baselines.load(ctx.definition.tenant_id, ctx.definition.id)
        reports = []
        for col in contract.drift.columns:
            if col not in baselines:
                continue
            report = compare_to_baseline(baselines[col], numeric_values(rows, col), contract.drift)
            if report is None:
                continue
            reports.append(report)
            if report.drifted:
                ctx.log.warning("drift", f"distribution drift on '{col}'", psi=report.psi,
                                ks=report.ks_statistic, mean_shift_sigma=report.mean_shift_sigma)
        return reports

    def _pipeline_error(self, ctx: _RunContext, ftype: FailureType, stage: str, exc: Exception) -> None:
        ctx.error = f"{type(exc).__name__}: {exc}"
        ctx.findings.append(Finding(category=FailureCategory.PIPELINE_FAILURE, failure_type=ftype,
                                    severity=Severity.HIGH, blocking=True, detail=ctx.error))
        ctx.log.error(stage, ctx.error)
        return None

    def _source_failure(self, ctx: _RunContext, exc: SourceError) -> None:
        ftype = {
            PartitionNotFound: FailureType.MISSING_PARTITION,
            MalformedPayload: FailureType.MALFORMED_JSON,
            ApiSchemaError: FailureType.API_SCHEMA_FAILURE,
        }.get(type(exc), FailureType.API_SCHEMA_FAILURE)
        ctx.error = str(exc)
        ctx.findings.append(Finding(category=FailureCategory.PIPELINE_FAILURE, failure_type=ftype,
                                    severity=Severity.CRITICAL if ftype == FailureType.MISSING_PARTITION else Severity.HIGH,
                                    blocking=True, detail=str(exc)))
        ctx.log.error("extract", str(exc), failure_type=ftype)

    # --- result ---

    def _finish(self, ctx: _RunContext, rows_loaded: int) -> RunResult:
        d = ctx.definition
        blocking = any(f.blocking for f in ctx.findings)
        status = (RunStatus.FAILED if blocking
                  else RunStatus.SUCCEEDED_WITH_WARNINGS if ctx.findings else RunStatus.SUCCEEDED)
        event = self._build_event(ctx, blocking) if ctx.findings else None

        if blocking and ctx.batch is not None:
            key = failed_partition_key(d.tenant_id, d.id, ctx.partition_id)
            self.object_store.put(key, ctx.batch.raw_payload.encode("utf-8"))
            ctx.log.info("quarantine", f"failed partition payload stored at {key}")

        ctx.log.info("finish", f"run {status}", rows_loaded=rows_loaded)
        return RunResult(
            run_id=ctx.run_id, tenant_id=d.tenant_id, pipeline_id=d.id, pipeline_version=d.version,
            partition_id=ctx.partition_id, status=status, started_at=ctx.started,
            finished_at=datetime.now(UTC), duration_ms=int((time.perf_counter() - ctx.t0) * 1000),
            rows_in=len(ctx.batch.records) if ctx.batch else 0, rows_loaded=rows_loaded,
            schema_version=ctx.observed_version, failure_event=event, logs=ctx.log.entries,
        )

    def _build_event(self, ctx: _RunContext, blocking: bool) -> FailureEvent:
        d = ctx.definition
        primary = classifier.primary_finding(ctx.findings)
        records = ctx.batch.records if ctx.batch else []
        if ctx.batch is not None and not ctx.profiles:
            ctx.profiles = profile_records(records)
        columns = sorted({f.column for f in ctx.findings if f.column})
        affected = len(ctx.affected) if ctx.affected else (len(records) if blocking else 0)
        return FailureEvent(
            tenant_id=d.tenant_id, pipeline_id=d.id, run_id=ctx.run_id, partition_id=ctx.partition_id,
            category=primary.category, failure_type=primary.failure_type, severity=primary.severity,
            blocking=blocking, summary=classifier.summarize(ctx.findings), affected_columns=columns,
            findings=ctx.findings, schema_diff=ctx.diff, expected_schema_version=ctx.expected_version,
            observed_schema_version=ctx.observed_version, violations=ctx.violations,
            drift_reports=[r for r in ctx.drift_reports if r.drifted],
            column_profiles={c: p for c, p in ctx.profiles.items() if c in columns} or ctx.profiles,
            sample_records=records[:SAMPLE_RECORDS], affected_records=affected, error_message=ctx.error,
        )
