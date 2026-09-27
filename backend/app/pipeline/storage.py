from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...


class LocalObjectStore:
    """Filesystem-backed S3-style store. Keys are validated so they cannot escape the root."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if not key or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in parts):
            raise ValueError(f"invalid object key {key!r}")
        path = (self._root / Path(*parts)).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError(f"object key escapes store root: {key!r}")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.exists():
            return []
        return sorted(p.relative_to(self._root).as_posix() for p in base.rglob("*") if p.is_file())


def failed_partition_key(tenant_id: str, pipeline_id: str, partition_id: str) -> str:
    return f"{tenant_id}/{pipeline_id}/failed/{partition_id}.json"
