import pytest

from app.core.types import DataType
from app.detection.profiling import profile_column


def test_numeric_strings_are_integer_like():
    p = profile_column("customer_id", ["1001", "1002", "1003"])
    assert p.physical_type == DataType.STRING
    assert p.integer_like_ratio == 1.0
    assert p.non_numeric_examples == []
    assert (p.min, p.max) == (1001, 1003)


def test_invalid_values_are_surfaced_as_examples():
    p = profile_column("customer_id", ["1001", "1002", "ABC123", "1004", None, "UNKNOWN"])
    assert p.null_count == 1
    assert p.integer_like_ratio == pytest.approx(3 / 5)
    assert p.non_numeric_examples == ["ABC123", "UNKNOWN"]


def test_blank_strings_count_as_nulls():
    p = profile_column("name", ["a", "  ", "", None])
    assert p.null_count == 3


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["27/09/2026 10:15:00", "01/10/2026 23:59:59"], "%d/%m/%Y %H:%M:%S"),
        (["2026-09-27T10:15:00"], "%Y-%m-%dT%H:%M:%S"),
        (["27/09/2026", "13/01/2026"], "%d/%m/%Y"),
    ],
)
def test_datetime_format_detection(values, expected):
    assert profile_column("created_at", values).best_datetime_format == expected


def test_ambiguous_day_month_prefers_day_first_only_when_evidence_supports_it():
    # 13/01 can only be day-first; 01/13 can only be month-first
    assert profile_column("d", ["01/13/2026", "02/14/2026"]).best_datetime_format == "%m/%d/%Y"


def test_email_ratio():
    p = profile_column("email", ["a@b.com", "bad", "c@d.org", "e@f"])
    assert p.email_like_ratio == 0.5
