from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from app.contracts.model import DataContract

IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def validate_identifier(name: str) -> str:
    if not IDENTIFIER_RE.match(name):
        raise ValueError(f"invalid identifier {name!r}: must match {IDENTIFIER_RE.pattern}")
    return name


class SourceConfig(BaseModel):
    kind: str
    entity: str
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


class PipelineDefinition(BaseModel):
    """Declarative pipeline. `transformations` maps each output column to a SQL
    expression over the staged source row; repairs are edits to this mapping."""

    id: str
    tenant_id: str
    name: str
    description: str = ""
    owner: str = ""
    version: int = 1
    source: SourceConfig
    contract: str
    target_table: str
    transformations: dict[str, str]

    @field_validator("id", "tenant_id", "target_table")
    @classmethod
    def _ident(cls, v: str) -> str:
        return validate_identifier(v)

    @field_validator("transformations")
    @classmethod
    def _columns(cls, v: dict[str, str]) -> dict[str, str]:
        for col in v:
            validate_identifier(col)
        return v

    @classmethod
    def from_yaml(cls, path: Path) -> PipelineDefinition:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def load_contract(self, config_dir: Path) -> DataContract:
        return DataContract.from_yaml(config_dir / "tenants" / self.tenant_id / self.contract)


def load_pipeline(config_dir: Path, tenant_id: str, pipeline_id: str) -> PipelineDefinition:
    validate_identifier(tenant_id)
    validate_identifier(pipeline_id)
    return PipelineDefinition.from_yaml(config_dir / "tenants" / tenant_id / "pipelines" / f"{pipeline_id}.yaml")
