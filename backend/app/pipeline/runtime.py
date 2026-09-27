from __future__ import annotations

from app.core.config import Settings
from app.detection.distribution import BaselineStore
from app.pipeline.engine import PipelineEngine
from app.pipeline.storage import LocalObjectStore
from app.pipeline.warehouse import Warehouse
from app.registry.service import SchemaRegistry
from app.registry.store import JsonFileSchemaStore


def build_engine(settings: Settings) -> PipelineEngine:
    return PipelineEngine(
        registry=SchemaRegistry(JsonFileSchemaStore(settings.registry_dir)),
        warehouse=Warehouse(settings.warehouse_path),
        baselines=BaselineStore(settings.baseline_dir),
        object_store=LocalObjectStore(settings.object_store_dir),
    )
