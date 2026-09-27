from app.core.types import DataType
from app.detection.schema_diff import ChangeKind, compare_schemas
from app.registry.models import FieldSpec, Schema

BASE = Schema(fields={
    "customer_id": FieldSpec(type=DataType.INTEGER, nullable=False, primary_key=True),
    "name": FieldSpec(type=DataType.STRING, nullable=False),
    "age": FieldSpec(type=DataType.INTEGER),
    "email": FieldSpec(type=DataType.STRING, nullable=False),
    "created_at": FieldSpec(type=DataType.TIMESTAMP, nullable=False),
})


def _with(**changes) -> Schema:
    fields = {k: v.model_copy() for k, v in BASE.fields.items()}
    for name, spec in changes.items():
        if spec is None:
            fields.pop(name)
        else:
            fields[name] = spec
    return Schema(fields=fields)


def test_identical_schemas_produce_empty_diff():
    diff = compare_schemas(BASE, _with())
    assert diff.is_empty and not diff.is_breaking
    assert diff.from_fingerprint == diff.to_fingerprint


def test_integer_to_string_is_breaking_type_change():
    diff = compare_schemas(BASE, _with(customer_id=FieldSpec(type=DataType.STRING, nullable=False, primary_key=True)))
    [change] = diff.changes
    assert change.kind == ChangeKind.TYPE_CHANGE
    assert (change.before, change.after) == (DataType.INTEGER, DataType.STRING)
    assert change.breaking


def test_widening_type_change_is_not_breaking():
    diff = compare_schemas(BASE, _with(age=FieldSpec(type=DataType.FLOAT)))
    [change] = diff.changes
    assert change.kind == ChangeKind.TYPE_CHANGE and not change.breaking


def test_added_column_is_non_breaking():
    diff = compare_schemas(BASE, _with(phone_number=FieldSpec(type=DataType.STRING)))
    [change] = diff.changes
    assert change.kind == ChangeKind.COLUMN_ADDED and not change.breaking
    assert not diff.is_breaking


def test_removed_column_is_breaking():
    diff = compare_schemas(BASE, _with(age=None))
    [change] = diff.changes
    assert change.kind == ChangeKind.COLUMN_REMOVED and change.breaking


def test_rename_detected_by_name_similarity():
    diff = compare_schemas(BASE, _with(email=None, email_address=FieldSpec(type=DataType.STRING, nullable=False)))
    [change] = diff.changes
    assert change.kind == ChangeKind.COLUMN_RENAMED
    assert (change.before, change.after) == ("email", "email_address")


def test_rename_detected_by_value_overlap_when_names_differ():
    observed = _with(email=None, contact=FieldSpec(type=DataType.STRING, nullable=False))
    values = [f"user{i}@example.com" for i in range(50)]
    diff = compare_schemas(BASE, observed, {"email": values}, {"contact": values})
    assert [c.kind for c in diff.changes] == [ChangeKind.COLUMN_RENAMED]


def test_unrelated_add_and_remove_are_not_merged_into_rename():
    diff = compare_schemas(BASE, _with(age=None, loyalty_tier=FieldSpec(type=DataType.STRING)))
    kinds = sorted(c.kind for c in diff.changes)
    assert kinds == [ChangeKind.COLUMN_ADDED, ChangeKind.COLUMN_REMOVED]


def test_rename_requires_matching_type():
    diff = compare_schemas(BASE, _with(email=None, email_address=FieldSpec(type=DataType.INTEGER, nullable=False)))
    assert ChangeKind.COLUMN_RENAMED not in {c.kind for c in diff.changes}


def test_relaxing_not_null_is_breaking_but_tightening_is_not():
    relaxed = compare_schemas(BASE, _with(email=FieldSpec(type=DataType.STRING, nullable=True)))
    tightened = compare_schemas(BASE, _with(age=FieldSpec(type=DataType.INTEGER, nullable=False)))
    assert relaxed.changes[0].kind == ChangeKind.NULLABILITY_CHANGE and relaxed.changes[0].breaking
    assert tightened.changes[0].kind == ChangeKind.NULLABILITY_CHANGE and not tightened.changes[0].breaking


def test_dropping_primary_key_is_breaking_constraint_change():
    diff = compare_schemas(BASE, _with(customer_id=FieldSpec(type=DataType.INTEGER, nullable=False)))
    [change] = diff.changes
    assert change.kind == ChangeKind.CONSTRAINT_CHANGE and change.breaking
