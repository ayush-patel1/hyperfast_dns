from datetime import datetime

from app.contracts.model import DataContract
from app.detection.quality import ViolationType, validate_contract


def _contract(**quality) -> DataContract:
    return DataContract.model_validate({
        "pipeline": "p",
        "schema": {
            "id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
            "age": {"type": "integer"},
            "status": {"type": "string"},
            "ts": {"type": "timestamp"},
        },
        "quality": quality,
    })


def _row(i, **kw):
    base = {"id": i, "email": f"u{i}@example.com", "age": 30, "status": "active", "ts": datetime(2026, 9, 27)}
    base.update(kw)
    return base


def _types(violations):
    return sorted((v.type, v.column) for v in violations)


def test_clean_rows_have_no_violations():
    rows = [_row(i) for i in range(10)]
    assert validate_contract(rows, _contract(id={"unique": True}, email={"format": "email"})) == []


def test_duplicates_nulls_formats_and_types():
    rows = [_row(1), _row(1), _row(2, email=None), _row(3, email="not-an-email"), _row(4, age="old")]
    violations = validate_contract(rows, _contract(id={"unique": True}, email={"format": "email"}))
    assert _types(violations) == sorted([
        (ViolationType.DUPLICATES, "id"),
        (ViolationType.UNEXPECTED_NULLS, "email"),
        (ViolationType.INVALID_FORMAT, "email"),
        (ViolationType.TYPE_MISMATCH, "age"),
    ])
    dup = next(v for v in violations if v.type == ViolationType.DUPLICATES)
    assert dup.row_indexes == [0, 1]


def test_range_enum_and_null_ratio():
    rows = [_row(i, age=150 if i == 0 else 30, status="gone" if i == 1 else "active",
                 ts=None if i < 5 else datetime(2026, 1, 1)) for i in range(10)]
    contract = _contract(age={"min": 0, "max": 120}, status={"allowed_values": ["active", "churned"]},
                         ts={"max_null_ratio": 0.2})
    assert _types(validate_contract(rows, contract)) == sorted([
        (ViolationType.OUT_OF_RANGE, "age"),
        (ViolationType.INVALID_ENUM, "status"),
        (ViolationType.UNEXPECTED_NULLS, "ts"),
    ])


def test_missing_contract_column():
    rows = [{k: v for k, v in _row(i).items() if k != "status"} for i in range(3)]
    assert _types(validate_contract(rows, _contract())) == [(ViolationType.MISSING_COLUMN, "status")]


def test_referential_integrity_uses_lookup():
    rows = [_row(i) for i in range(5)]
    contract = _contract(id={"references": {"table": "accounts", "column": "id"}})
    violations = validate_contract(rows, contract, reference_lookup=lambda t, c: {"0", "1", "2"})
    [v] = violations
    assert v.type == ViolationType.REFERENTIAL_INTEGRITY and v.failing_rows == 2


def test_iqr_outliers():
    rows = [_row(i, age=30 + (i % 5)) for i in range(40)] + [_row(99, age=900)]
    violations = validate_contract(rows, _contract(age={"outlier_iqr_k": 3}))
    assert _types(violations) == [(ViolationType.OUTLIERS, "age")]
