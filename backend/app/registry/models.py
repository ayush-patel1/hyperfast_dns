from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.types import DataType


class FieldSpec(BaseModel):
    type: DataType
    nullable: bool = True
    primary_key: bool = False


class Schema(BaseModel):
    fields: dict[str, FieldSpec]

    @classmethod
    def of(cls, spec: dict[str, str | DataType | FieldSpec]) -> Schema:
        fields = {}
        for name, value in spec.items():
            if isinstance(value, FieldSpec):
                fields[name] = value
            else:
                fields[name] = FieldSpec(type=DataType.parse(str(value)))
        return cls(fields=fields)

    def fingerprint(self) -> str:
        canonical = json.dumps(
            {k: v.model_dump(mode="json") for k, v in sorted(self.fields.items())}, sort_keys=True
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def types(self) -> dict[str, DataType]:
        return {k: v.type for k, v in self.fields.items()}


class SchemaStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    OBSERVED = "OBSERVED"  # seen upstream but not yet approved for the pipeline
    REJECTED = "REJECTED"


class SchemaVersion(BaseModel):
    tenant_id: str
    pipeline_id: str
    version: int
    schema_: Schema = Field(alias="schema")
    fingerprint: str
    status: SchemaStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""

    model_config = {"populate_by_name": True}
