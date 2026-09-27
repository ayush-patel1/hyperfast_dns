"""Value-level column profiling.

Physical types say what the upstream *declared*; profiles say what the values
actually *look like*. The gap between the two is what makes a repair safe or not.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Any, Iterable

from pydantic import BaseModel, Field

from app.core.types import DataType, physical_type

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# strptime patterns; identical in Python and DuckDB so a detected format can be
# used verbatim inside a generated SQL repair.
DATETIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)

MAX_EXAMPLES = 5


class ColumnProfile(BaseModel):
    column: str
    physical_type: DataType
    count: int
    null_count: int
    distinct_count: int
    null_ratio: float
    integer_like_ratio: float = 0.0
    numeric_like_ratio: float = 0.0
    email_like_ratio: float = 0.0
    datetime_format_ratios: dict[str, float] = Field(default_factory=dict)
    non_numeric_examples: list[str] = Field(default_factory=list)
    top_values: list[tuple[str, int]] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None

    @property
    def best_datetime_format(self) -> str | None:
        """Format parsing the most values; ties resolved by DATETIME_FORMATS order."""
        if not self.datetime_format_ratios:
            return None
        best = max(self.datetime_format_ratios.values())
        for fmt in DATETIME_FORMATS:
            if self.datetime_format_ratios.get(fmt) == best:
                return fmt
        return None


def _parses(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value, fmt)
        return True
    except ValueError:
        return False


def _dominant_type(values: list[Any]) -> DataType:
    types = Counter(physical_type(v) for v in values if v is not None)
    if not types:
        return DataType.NULL
    return types.most_common(1)[0][0]


def profile_column(column: str, values: Iterable[Any]) -> ColumnProfile:
    values = list(values)
    count = len(values)
    non_null = [v for v in values if v is not None and not (isinstance(v, str) and v.strip() == "")]
    null_count = count - len(non_null)
    as_str = [str(v).strip() for v in non_null]
    n = len(as_str)

    profile = ColumnProfile(
        column=column,
        physical_type=_dominant_type(values),
        count=count,
        null_count=null_count,
        distinct_count=len(set(as_str)),
        null_ratio=(null_count / count) if count else 0.0,
        top_values=Counter(as_str).most_common(5),
    )
    if n == 0:
        return profile

    int_like = [s for s in as_str if INT_RE.match(s)]
    num_like = [s for s in as_str if FLOAT_RE.match(s)]
    profile.integer_like_ratio = len(int_like) / n
    profile.numeric_like_ratio = len(num_like) / n
    profile.email_like_ratio = sum(1 for s in as_str if EMAIL_RE.match(s)) / n
    profile.non_numeric_examples = sorted({s for s in as_str if not FLOAT_RE.match(s)})[:MAX_EXAMPLES]

    if num_like:
        nums = [float(s) for s in num_like]
        mean = sum(nums) / len(nums)
        var = sum((x - mean) ** 2 for x in nums) / len(nums)
        profile.min, profile.max = min(nums), max(nums)
        profile.mean, profile.std = mean, math.sqrt(var)

    if profile.physical_type in (DataType.STRING, DataType.TIMESTAMP, DataType.DATE):
        for fmt in DATETIME_FORMATS:
            ratio = sum(1 for s in as_str if _parses(s, fmt)) / n
            if ratio > 0:
                profile.datetime_format_ratios[fmt] = round(ratio, 4)
    return profile


def profile_records(records: list[dict[str, Any]], columns: Iterable[str] | None = None) -> dict[str, ColumnProfile]:
    cols = list(columns) if columns is not None else sorted({k for r in records for k in r})
    return {c: profile_column(c, (r.get(c) for r in records)) for c in cols}
