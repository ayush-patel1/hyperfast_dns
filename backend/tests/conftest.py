from __future__ import annotations

import logging

import pytest

from app.contracts.model import DataContract
from app.core.config import REPO_ROOT, Settings
from app.pipeline.definition import PipelineDefinition, load_pipeline
from app.pipeline.engine import PipelineEngine
from app.pipeline.runtime import build_engine
from app.pipeline.simulator import SimulatedCustomerSource

logging.disable(logging.CRITICAL)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", config_dir=REPO_ROOT / "config")


@pytest.fixture
def engine(settings) -> PipelineEngine:
    return build_engine(settings)


@pytest.fixture
def definition(settings) -> PipelineDefinition:
    return load_pipeline(settings.config_dir, "acme", "customer_pipeline")


@pytest.fixture
def contract(settings, definition) -> DataContract:
    return definition.load_contract(settings.config_dir)


@pytest.fixture
def source() -> SimulatedCustomerSource:
    return SimulatedCustomerSource(rows=300)
