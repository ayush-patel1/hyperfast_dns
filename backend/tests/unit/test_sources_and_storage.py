import json

import pytest

from app.core.types import DataType
from app.pipeline.sources import ApiSchemaError, MalformedPayload, infer_schema, parse_envelope
from app.pipeline.storage import LocalObjectStore


def test_envelope_with_declared_schema():
    raw = json.dumps({"schema": {"fields": {"id": {"type": "INTEGER", "nullable": False}}},
                      "records": [{"id": 1}]})
    batch = parse_envelope("src", "p1", raw)
    assert batch.schema_declared and batch.schema_.fields["id"].type == DataType.INTEGER


def test_envelope_without_schema_is_inferred():
    raw = json.dumps({"records": [{"id": 1, "ts": "2026-09-27T10:00:00", "score": 1.5, "tag": None},
                                  {"id": 2, "ts": "2026-09-27 11:00:00", "score": 2, "tag": "x"}]})
    batch = parse_envelope("api", "p1", raw)
    types = batch.schema_.types()
    assert not batch.schema_declared
    assert types == {"id": DataType.INTEGER, "ts": DataType.TIMESTAMP, "score": DataType.FLOAT, "tag": DataType.STRING}
    assert batch.schema_.fields["tag"].nullable and not batch.schema_.fields["id"].nullable


def test_mixed_types_infer_as_string():
    assert infer_schema([{"v": 1}, {"v": "x"}]).fields["v"].type == DataType.STRING


def test_malformed_json():
    with pytest.raises(MalformedPayload):
        parse_envelope("src", "p1", '{"records": [')


@pytest.mark.parametrize("raw", ['[1,2]', '{"rows": []}', '{"records": [1]}',
                                 '{"schema": {"fields": {"a": {"type": "NOPE"}}}, "records": []}'])
def test_api_schema_errors(raw):
    with pytest.raises(ApiSchemaError):
        parse_envelope("src", "p1", raw)


def test_object_store_round_trip_and_listing(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put("acme/p/failed/2026-09-27.json", b"{}")
    assert store.get("acme/p/failed/2026-09-27.json") == b"{}"
    assert store.list("acme/p") == ["acme/p/failed/2026-09-27.json"]


@pytest.mark.parametrize("key", ["../escape.json", "/abs.json", "acme/../../x", "a//b", "C:/x", "a\\..\\b", ""])
def test_object_store_rejects_path_traversal(tmp_path, key):
    with pytest.raises(ValueError):
        LocalObjectStore(tmp_path).put(key, b"x")
