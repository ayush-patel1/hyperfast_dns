"""Source adapters.

Every source ultimately yields a `SourceBatch`: one partition of records plus the
schema the upstream *declared* (Kafka Connect style envelope). Sources without a
declared schema (plain REST APIs) get one inferred from their values.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.core.types import DataType, physical_type
from app.registry.models import FieldSpec, Schema

PARTITION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


class SourceError(Exception):
    """Base class for failures before any record reaches the pipeline."""


class PartitionNotFound(SourceError):
    pass


class MalformedPayload(SourceError):
    pass


class ApiSchemaError(SourceError):
    pass


class SourceBatch(BaseModel):
    source: str
    partition_id: str
    schema_: Schema = Field(alias="schema")
    records: list[dict[str, Any]]
    raw_payload: str
    schema_declared: bool = True

    model_config = {"populate_by_name": True}


class Source(Protocol):
    name: str

    def fetch(self, partition_id: str) -> SourceBatch: ...


def validate_partition_id(partition_id: str) -> str:
    if not PARTITION_RE.match(partition_id):
        raise ValueError(f"invalid partition id {partition_id!r}")
    return partition_id


def _looks_iso_timestamp(values: list[str]) -> bool:
    def ok(s: str) -> bool:
        for fmt in _ISO_FORMATS:
            try:
                datetime.strptime(s, fmt)
                return True
            except ValueError:
                continue
        return False
    return bool(values) and all(ok(v) for v in values)


def infer_schema(records: list[dict[str, Any]]) -> Schema:
    columns: dict[str, list[Any]] = {}
    for r in records:
        for k, v in r.items():
            columns.setdefault(k, []).append(v)
    fields: dict[str, FieldSpec] = {}
    for col, values in columns.items():
        non_null = [v for v in values if v is not None]
        types = {physical_type(v) for v in non_null}
        if not types:
            dtype = DataType.STRING
        elif types == {DataType.INTEGER}:
            dtype = DataType.INTEGER
        elif types <= {DataType.INTEGER, DataType.FLOAT}:
            dtype = DataType.FLOAT
        elif types == {DataType.STRING} and _looks_iso_timestamp(non_null):
            dtype = DataType.TIMESTAMP
        elif len(types) == 1:
            dtype = types.pop()
        else:
            dtype = DataType.STRING
        missing = len(values) < len(records)
        fields[col] = FieldSpec(type=dtype, nullable=missing or len(non_null) < len(values))
    return Schema(fields=fields)


def parse_envelope(source: str, partition_id: str, raw: str) -> SourceBatch:
    """Parse `{"schema": {"fields": {...}}, "records": [...]}`; schema is optional."""
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedPayload(f"partition {partition_id}: invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("records"), list):
        raise ApiSchemaError(f"partition {partition_id}: envelope must be an object with a 'records' array")
    records = doc["records"]
    if not all(isinstance(r, dict) for r in records):
        raise ApiSchemaError(f"partition {partition_id}: every record must be a JSON object")

    declared = doc.get("schema")
    if declared is None:
        return SourceBatch(source=source, partition_id=partition_id, schema=infer_schema(records),
                           records=records, raw_payload=raw, schema_declared=False)
    try:
        schema = Schema.model_validate(declared)
    except ValidationError as exc:
        raise ApiSchemaError(f"partition {partition_id}: invalid declared schema: {exc.errors()[0]['msg']}") from exc
    return SourceBatch(source=source, partition_id=partition_id, schema=schema, records=records, raw_payload=raw)
