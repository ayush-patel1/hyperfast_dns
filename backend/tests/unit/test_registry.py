import pytest

from app.registry.models import Schema, SchemaStatus
from app.registry.service import SchemaRegistry
from app.registry.store import InMemorySchemaStore, JsonFileSchemaStore

V1 = Schema.of({"customer_id": "INTEGER", "name": "STRING"})
V2 = Schema.of({"customer_id": "STRING", "name": "STRING"})


@pytest.fixture(params=["memory", "json"])
def registry(request, tmp_path) -> SchemaRegistry:
    store = InMemorySchemaStore() if request.param == "memory" else JsonFileSchemaStore(tmp_path)
    return SchemaRegistry(store)


def test_versions_increment_and_latest_accepted(registry):
    v1 = registry.record("acme", "p", V1, SchemaStatus.ACCEPTED)
    v2 = registry.record("acme", "p", V2, SchemaStatus.OBSERVED)
    assert (v1.version, v2.version) == (1, 2)
    assert registry.latest_accepted("acme", "p").version == 1


def test_recording_known_schema_is_idempotent(registry):
    registry.record("acme", "p", V1, SchemaStatus.ACCEPTED)
    again = registry.record("acme", "p", Schema.of({"customer_id": "INT", "name": "TEXT"}), SchemaStatus.OBSERVED)
    assert again.version == 1 and len(registry.history("acme", "p")) == 1


def test_accepting_observed_version_promotes_it(registry):
    registry.record("acme", "p", V1, SchemaStatus.ACCEPTED)
    registry.record("acme", "p", V2, SchemaStatus.OBSERVED)
    promoted = registry.record("acme", "p", V2, SchemaStatus.ACCEPTED, reason="repair approved")
    assert promoted.version == 2 and promoted.status == SchemaStatus.ACCEPTED
    assert registry.latest_accepted("acme", "p").version == 2


def test_tenants_are_isolated(registry):
    registry.record("acme", "p", V1, SchemaStatus.ACCEPTED)
    assert registry.history("globex", "p") == []
    assert registry.latest_accepted("globex", "p") is None


def test_set_status_unknown_version_raises(registry):
    with pytest.raises(KeyError):
        registry.set_status("acme", "p", 99, SchemaStatus.REJECTED)


def test_json_store_round_trip(tmp_path):
    SchemaRegistry(JsonFileSchemaStore(tmp_path)).record("acme", "p", V1, SchemaStatus.ACCEPTED)
    reloaded = SchemaRegistry(JsonFileSchemaStore(tmp_path)).latest_accepted("acme", "p")
    assert reloaded.schema_ == V1 and reloaded.fingerprint == V1.fingerprint()
