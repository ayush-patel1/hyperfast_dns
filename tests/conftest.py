from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_dir() -> Path:
    return Path(os.environ.get("HFDNS_BUILD_DIR", Path.home() / "build" / "hfdns"))


@pytest.fixture(scope="session")
def lb_binary() -> Path:
    path = _build_dir() / "core" / "hfdns-lb"
    if not path.is_file():
        pytest.fail(f"{path} not found: run `make build` first (or set HFDNS_BUILD_DIR)")
    return path


@pytest.fixture(scope="session")
def repo_config_dir() -> Path:
    return REPO_ROOT / "config"
