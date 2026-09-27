from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Protocol

from app.registry.models import SchemaVersion


class SchemaStore(Protocol):
    def list_versions(self, tenant_id: str, pipeline_id: str) -> list[SchemaVersion]: ...
    def save(self, version: SchemaVersion) -> None: ...


class InMemorySchemaStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], list[SchemaVersion]] = {}

    def list_versions(self, tenant_id: str, pipeline_id: str) -> list[SchemaVersion]:
        return list(self._data.get((tenant_id, pipeline_id), []))

    def save(self, version: SchemaVersion) -> None:
        versions = self._data.setdefault((version.tenant_id, version.pipeline_id), [])
        versions[:] = [v for v in versions if v.version != version.version] + [version]
        versions.sort(key=lambda v: v.version)


class JsonFileSchemaStore:
    """One JSON document per tenant/pipeline. Replaced by the SQL store in the API service."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.Lock()

    def _path(self, tenant_id: str, pipeline_id: str) -> Path:
        return self._root / tenant_id / f"{pipeline_id}.schemas.json"

    def list_versions(self, tenant_id: str, pipeline_id: str) -> list[SchemaVersion]:
        path = self._path(tenant_id, pipeline_id)
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [SchemaVersion.model_validate(v) for v in raw]

    def save(self, version: SchemaVersion) -> None:
        with self._lock:
            existing = [v for v in self.list_versions(version.tenant_id, version.pipeline_id)
                        if v.version != version.version]
            existing.append(version)
            existing.sort(key=lambda v: v.version)
            path = self._path(version.tenant_id, version.pipeline_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = [v.model_dump(mode="json", by_alias=True) for v in existing]
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
