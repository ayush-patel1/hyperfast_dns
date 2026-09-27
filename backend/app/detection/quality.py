"""Contract-driven data-quality validation of transformed output."""
from __future__ import annotations

import re
from collections import Counter
from enum import StrEnum
from typing import Any, Callable

import numpy as np
from pydantic import BaseModel, Field

from app.contracts.model import DataContract
from app.core.types import DataType, physical_type
from app.detection.profiling import EMAIL_RE

MAX_EXAMPLES = 5

NAMED_FORMATS: dict[str, re.Pattern[str]] = {
    "email": EMAIL_RE,
    "phone": re.compile(r"^\+?[0-9 ()-]{7,20}$"),
    "uuid": re.compile(r"^[0-9a-fA-F-]{36}$"),
}


class ViolationType(StrEnum):
    TYPE_MISMATCH = "TYPE_MISMATCH"
    MISSING_COLUMN = "MISSING_COLUMN"
    UNEXPECTED_NULLS = "UNEXPECTED_NULLS"
    DUPLICATES = "DUPLICATES"
    INVALID_FORMAT = "INVALID_FORMAT"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    OUTLIERS = "OUTLIERS"
    INVALID_ENUM = "INVALID_ENUM"
    REFERENTIAL_INTEGRITY = "REFERENTIAL_INTEGRITY"


class Violation(BaseModel):
    type: ViolationType
    column: str
    failing_rows: int
    total_rows: int
    examples: list[str] = Field(default_factory=list)
    row_indexes: list[int] = Field(default_factory=list)
    detail: str

    @property
    def ratio(self) -> float:
        return self.failing_rows / self.total_rows if self.total_rows else 0.0


ReferenceLookup = Callable[[str, str], set[str]]


def _violation(vt: ViolationType, col: str, idx: list[int], rows: list[dict[str, Any]], detail: str) -> Violation:
    return Violation(
        type=vt, column=col, failing_rows=len(idx), total_rows=len(rows),
        examples=[repr(rows[i].get(col)) for i in idx[:MAX_EXAMPLES]],
        row_indexes=idx, detail=detail,
    )


def _type_ok(value: Any, expected: DataType) -> bool:
    actual = physical_type(value)
    if actual == DataType.NULL or actual == expected:
        return True
    return expected == DataType.FLOAT and actual == DataType.INTEGER


def validate_contract(
    rows: list[dict[str, Any]],
    contract: DataContract,
    reference_lookup: ReferenceLookup | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
    if not rows:
        return violations
    present = set().union(*(r.keys() for r in rows))

    for col, field in contract.schema_.items():
        if col not in present:
            violations.append(Violation(
                type=ViolationType.MISSING_COLUMN, column=col, failing_rows=len(rows),
                total_rows=len(rows), detail=f"contract column '{col}' missing from output",
            ))
            continue
        values = [r.get(col) for r in rows]

        bad_type = [i for i, v in enumerate(values) if not _type_ok(v, field.type)]
        if bad_type:
            violations.append(_violation(ViolationType.TYPE_MISMATCH, col, bad_type, rows,
                                         f"{len(bad_type)} values are not {field.type}"))

        nulls = [i for i, v in enumerate(values) if v is None]
        rule = contract.rule(col)
        if nulls and not field.nullable:
            violations.append(_violation(ViolationType.UNEXPECTED_NULLS, col, nulls, rows,
                                         f"{len(nulls)} nulls in NOT NULL column"))
        elif rule.max_null_ratio is not None and len(nulls) / len(rows) > rule.max_null_ratio:
            violations.append(_violation(ViolationType.UNEXPECTED_NULLS, col, nulls, rows,
                                         f"null ratio {len(nulls)/len(rows):.2%} > {rule.max_null_ratio:.2%}"))

        non_null = [(i, v) for i, v in enumerate(values) if v is not None]
        if rule.unique or field.primary_key:
            counts = Counter(str(v) for _, v in non_null)
            dup = [i for i, v in non_null if counts[str(v)] > 1]
            if dup:
                violations.append(_violation(ViolationType.DUPLICATES, col, dup, rows,
                                             f"{len(dup)} rows share duplicate keys"))

        pattern = NAMED_FORMATS.get(rule.format or "") or (re.compile(rule.pattern) if rule.pattern else None)
        if pattern is not None:
            bad = [i for i, v in non_null if not pattern.match(str(v))]
            if bad:
                violations.append(_violation(ViolationType.INVALID_FORMAT, col, bad, rows,
                                             f"{len(bad)} values do not match format {rule.format or rule.pattern}"))

        if rule.allowed_values is not None:
            allowed = set(rule.allowed_values)
            bad = [i for i, v in non_null if str(v) not in allowed]
            if bad:
                violations.append(_violation(ViolationType.INVALID_ENUM, col, bad, rows,
                                             f"{len(bad)} values outside allowed set"))

        numeric = [(i, float(v)) for i, v in non_null
                   if physical_type(v) in (DataType.INTEGER, DataType.FLOAT)]
        if numeric and (rule.min is not None or rule.max is not None):
            bad = [i for i, x in numeric
                   if (rule.min is not None and x < rule.min) or (rule.max is not None and x > rule.max)]
            if bad:
                violations.append(_violation(ViolationType.OUT_OF_RANGE, col, bad, rows,
                                             f"{len(bad)} values outside [{rule.min}, {rule.max}]"))

        if numeric and rule.outlier_iqr_k is not None and len(numeric) >= 20:
            arr = np.array([x for _, x in numeric])
            q1, q3 = np.percentile(arr, [25, 75])
            spread = (q3 - q1) * rule.outlier_iqr_k
            bad = [i for i, x in numeric if x < q1 - spread or x > q3 + spread]
            if bad:
                violations.append(_violation(ViolationType.OUTLIERS, col, bad, rows,
                                             f"{len(bad)} IQR outliers (k={rule.outlier_iqr_k})"))

        if rule.references is not None and reference_lookup is not None:
            known = reference_lookup(rule.references.table, rule.references.column)
            bad = [i for i, v in non_null if str(v) not in known]
            if bad:
                violations.append(_violation(
                    ViolationType.REFERENTIAL_INTEGRITY, col, bad, rows,
                    f"{len(bad)} values missing in {rule.references.table}.{rule.references.column}",
                ))
    return violations
