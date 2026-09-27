from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _path_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).resolve() if raw else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _path_env("SELFHEAL_DATA_DIR", REPO_ROOT / "data"))
    config_dir: Path = field(default_factory=lambda: _path_env("SELFHEAL_CONFIG_DIR", REPO_ROOT / "config"))

    @property
    def warehouse_path(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    @property
    def registry_dir(self) -> Path:
        return self.data_dir / "registry"

    @property
    def baseline_dir(self) -> Path:
        return self.data_dir / "baselines"

    @property
    def object_store_dir(self) -> Path:
        return self.data_dir / "objects"


def get_settings() -> Settings:
    return Settings()
