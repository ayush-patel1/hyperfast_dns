from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from app.core.types import DataType
from app.registry.models import FieldSpec, Schema


class ReferenceSpec(BaseModel):
    table: str
    column: str


class ColumnRule(BaseModel):
    unique: bool = False
    format: str | None = None  # "email" or a named/regex format
    pattern: str | None = None
    min: float | None = None
    max: float | None = None
    allowed_values: list[str] | None = None
    references: ReferenceSpec | None = None
    max_null_ratio: float | None = None
    outlier_iqr_k: float | None = None


class DriftAction(StrEnum):
    WARN = "warn"
    BLOCK = "block"


class DriftPolicy(BaseModel):
    columns: list[str] = Field(default_factory=list)
    psi_threshold: float = 0.25
    ks_threshold: float = 0.3
    mean_shift_sigma: float = 3.0
    min_baseline: int = 200
    action: DriftAction = DriftAction.BLOCK


class ContractField(BaseModel):
    type: DataType
    nullable: bool = True
    primary_key: bool = False

    @field_validator("type", mode="before")
    @classmethod
    def _parse_type(cls, v: object) -> DataType:
        return v if isinstance(v, DataType) else DataType.parse(str(v))


class DataContract(BaseModel):
    """Output contract of a pipeline: what the warehouse table guarantees consumers."""

    pipeline: str
    version: int = 1
    schema_: dict[str, ContractField] = Field(alias="schema")
    quality: dict[str, ColumnRule] = Field(default_factory=dict)
    drift: DriftPolicy = Field(default_factory=DriftPolicy)

    model_config = {"populate_by_name": True}

    @classmethod
    def from_yaml(cls, path: Path) -> DataContract:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def as_schema(self) -> Schema:
        return Schema(fields={
            name: FieldSpec(type=f.type, nullable=f.nullable, primary_key=f.primary_key)
            for name, f in self.schema_.items()
        })

    def rule(self, column: str) -> ColumnRule:
        return self.quality.get(column, ColumnRule())
