from __future__ import annotations

from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.types import is_widening
from app.registry.models import Schema

RENAME_NAME_SIMILARITY = 0.6
RENAME_VALUE_OVERLAP = 0.8


class ChangeKind(StrEnum):
    TYPE_CHANGE = "TYPE_CHANGE"
    COLUMN_ADDED = "COLUMN_ADDED"
    COLUMN_REMOVED = "COLUMN_REMOVED"
    COLUMN_RENAMED = "COLUMN_RENAMED"
    NULLABILITY_CHANGE = "NULLABILITY_CHANGE"
    CONSTRAINT_CHANGE = "CONSTRAINT_CHANGE"


class SchemaChange(BaseModel):
    kind: ChangeKind
    column: str
    before: str | None = None
    after: str | None = None
    breaking: bool
    detail: str


class SchemaDiff(BaseModel):
    from_fingerprint: str
    to_fingerprint: str
    from_version: int | None = None
    to_version: int | None = None
    changes: list[SchemaChange] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.changes

    @property
    def is_breaking(self) -> bool:
        return any(c.breaking for c in self.changes)

    def by_kind(self, kind: ChangeKind) -> list[SchemaChange]:
        return [c for c in self.changes if c.kind == kind]


def _name_similarity(old: str, new: str) -> float:
    a, b = old.lower(), new.lower()
    score = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = set(a.split("_")), set(b.split("_"))
    if tokens_a <= tokens_b or tokens_b <= tokens_a:  # email -> email_address, cust_id -> id
        score = max(score, 0.75)
    return score


def _value_overlap(a: list[Any], b: list[Any]) -> float:
    sa = {str(v) for v in a if v is not None}
    sb = {str(v) for v in b if v is not None}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def compare_schemas(
    expected: Schema,
    observed: Schema,
    expected_samples: dict[str, list[Any]] | None = None,
    observed_samples: dict[str, list[Any]] | None = None,
) -> SchemaDiff:
    """Structured diff from the accepted schema to what upstream now sends.

    Renames are inferred from a removed/added pair with the same type whose names
    are similar or whose sampled values overlap; they are never assumed.
    """
    diff = SchemaDiff(from_fingerprint=expected.fingerprint(), to_fingerprint=observed.fingerprint())
    exp, obs = expected.fields, observed.fields
    removed = [c for c in exp if c not in obs]
    added = [c for c in obs if c not in exp]

    for old in list(removed):
        best: tuple[float, str] | None = None
        for new in added:
            if exp[old].type != obs[new].type:
                continue
            score = _name_similarity(old, new)
            if expected_samples and observed_samples:
                overlap = _value_overlap(expected_samples.get(old, []), observed_samples.get(new, []))
                if overlap >= RENAME_VALUE_OVERLAP:
                    score = max(score, overlap)
            if score >= RENAME_NAME_SIMILARITY and (best is None or score > best[0]):
                best = (score, new)
        if best:
            new = best[1]
            removed.remove(old)
            added.remove(new)
            diff.changes.append(SchemaChange(
                kind=ChangeKind.COLUMN_RENAMED, column=old, before=old, after=new, breaking=True,
                detail=f"column '{old}' appears renamed to '{new}' (match score {best[0]:.2f})",
            ))

    for col in removed:
        diff.changes.append(SchemaChange(
            kind=ChangeKind.COLUMN_REMOVED, column=col, before=exp[col].type, breaking=True,
            detail=f"column '{col}' ({exp[col].type}) no longer present upstream",
        ))
    for col in added:
        diff.changes.append(SchemaChange(
            kind=ChangeKind.COLUMN_ADDED, column=col, after=obs[col].type,
            breaking=False,  # transformations select explicit columns, so extras are ignored
            detail=f"new column '{col}' ({obs[col].type}) appeared upstream",
        ))

    for col in exp.keys() & obs.keys():
        e, o = exp[col], obs[col]
        if e.type != o.type:
            widening = is_widening(e.type, o.type)
            diff.changes.append(SchemaChange(
                kind=ChangeKind.TYPE_CHANGE, column=col, before=e.type, after=o.type,
                breaking=not widening,
                detail=f"'{col}' changed {e.type} -> {o.type}" + (" (widening)" if widening else ""),
            ))
        if e.nullable != o.nullable:
            diff.changes.append(SchemaChange(
                kind=ChangeKind.NULLABILITY_CHANGE, column=col,
                before="NULLABLE" if e.nullable else "NOT NULL",
                after="NULLABLE" if o.nullable else "NOT NULL",
                breaking=o.nullable,  # relaxing NOT NULL can leak nulls downstream
                detail=f"'{col}' nullability changed",
            ))
        if e.primary_key != o.primary_key:
            diff.changes.append(SchemaChange(
                kind=ChangeKind.CONSTRAINT_CHANGE, column=col,
                before="PRIMARY KEY" if e.primary_key else "NONE",
                after="PRIMARY KEY" if o.primary_key else "NONE",
                breaking=e.primary_key,
                detail=f"'{col}' primary-key constraint changed",
            ))

    order = {c: i for i, c in enumerate(list(exp) + [c for c in obs if c not in exp])}
    diff.changes.sort(key=lambda c: (order.get(c.column, 1_000), c.kind))
    return diff
