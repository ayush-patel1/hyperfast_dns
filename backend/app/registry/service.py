from __future__ import annotations

from app.registry.models import Schema, SchemaStatus, SchemaVersion
from app.registry.store import SchemaStore


class SchemaRegistry:
    """Versioned source-schema registry.

    The *accepted* version is what the pipeline's transformations are written
    against. New upstream shapes are recorded as OBSERVED until a repair (or a
    human) accepts them.
    """

    def __init__(self, store: SchemaStore) -> None:
        self._store = store

    def history(self, tenant_id: str, pipeline_id: str) -> list[SchemaVersion]:
        return self._store.list_versions(tenant_id, pipeline_id)

    def get(self, tenant_id: str, pipeline_id: str, version: int) -> SchemaVersion | None:
        return next((v for v in self.history(tenant_id, pipeline_id) if v.version == version), None)

    def latest_accepted(self, tenant_id: str, pipeline_id: str) -> SchemaVersion | None:
        accepted = [v for v in self.history(tenant_id, pipeline_id) if v.status == SchemaStatus.ACCEPTED]
        return accepted[-1] if accepted else None

    def find_by_fingerprint(self, tenant_id: str, pipeline_id: str, fingerprint: str) -> SchemaVersion | None:
        matches = [v for v in self.history(tenant_id, pipeline_id) if v.fingerprint == fingerprint]
        return matches[-1] if matches else None

    def record(
        self,
        tenant_id: str,
        pipeline_id: str,
        schema: Schema,
        status: SchemaStatus,
        reason: str = "",
    ) -> SchemaVersion:
        """Idempotent on schema fingerprint: re-observing a known shape returns the existing version."""
        fingerprint = schema.fingerprint()
        existing = self.find_by_fingerprint(tenant_id, pipeline_id, fingerprint)
        if existing is not None:
            if status == SchemaStatus.ACCEPTED and existing.status != SchemaStatus.ACCEPTED:
                return self.set_status(tenant_id, pipeline_id, existing.version, status, reason)
            return existing

        history = self.history(tenant_id, pipeline_id)
        version = SchemaVersion(
            tenant_id=tenant_id,
            pipeline_id=pipeline_id,
            version=(history[-1].version + 1) if history else 1,
            schema=schema,
            fingerprint=fingerprint,
            status=status,
            reason=reason,
        )
        self._store.save(version)
        return version

    def set_status(
        self, tenant_id: str, pipeline_id: str, version: int, status: SchemaStatus, reason: str = ""
    ) -> SchemaVersion:
        current = self.get(tenant_id, pipeline_id, version)
        if current is None:
            raise KeyError(f"schema version {version} not found for {tenant_id}/{pipeline_id}")
        updated = current.model_copy(update={"status": status, "reason": reason or current.reason})
        self._store.save(updated)
        return updated
