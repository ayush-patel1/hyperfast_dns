"""Deterministic upstream simulator for the `customers` entity.

It plays the role of an upstream team: the same partition always produces the
same records, and switching `scenario` changes the upstream contract exactly the
way real producers break things.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.core.types import DataType
from app.pipeline.sources import PartitionNotFound, SourceBatch, parse_envelope, validate_partition_id

FIRST_NAMES = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Zara", "Ethan", "Isha", "Lucas", "Anaya",
               "Oliver", "Mei", "Arjun", "Chloe", "Mateo", "Priya", "Leo", "Amara", "Kai", "Nora"]
LAST_NAMES = ["Sharma", "Garcia", "Chen", "Patel", "Okafor", "Silva", "Novak", "Kim", "Rossi", "Haddad",
              "Mehta", "Johansson", "Ito", "Dubois", "Kowalski", "Reyes", "Singh", "Muller", "Lee", "Walker"]
DOMAINS = ["example.com", "mail.test", "corp.example", "inbox.test"]
INVALID_IDS = ["ABC123", "UNKNOWN", "N/A", "#REF!"]
EPOCH = date(2026, 1, 1)


class Scenario(StrEnum):
    HEALTHY = "healthy"
    TYPE_DRIFT = "type_drift"
    DATE_FORMAT_DRIFT = "date_format_drift"
    INVALID_VALUES = "invalid_values"
    NEW_COLUMN = "new_column"
    SEMANTIC_DRIFT = "semantic_drift"
    COLUMN_RENAME = "column_rename"
    COLUMN_REMOVED = "column_removed"
    NULLABILITY_CHANGE = "nullability_change"
    DUPLICATES = "duplicates"
    MALFORMED_JSON = "malformed_json"
    MISSING_PARTITION = "missing_partition"


BASE_SCHEMA: dict[str, dict[str, Any]] = {
    "customer_id": {"type": DataType.INTEGER, "nullable": False, "primary_key": True},
    "name": {"type": DataType.STRING, "nullable": False},
    "age": {"type": DataType.INTEGER, "nullable": True},
    "email": {"type": DataType.STRING, "nullable": False},
    "created_at": {"type": DataType.TIMESTAMP, "nullable": False},
}


def _partition_base(partition_id: str, rows: int) -> int:
    try:
        index = (date.fromisoformat(partition_id) - EPOCH).days
    except ValueError:
        index = int(hashlib.sha256(partition_id.encode()).hexdigest()[:6], 16) % 50_000
    return 1001 + max(index, 0) * rows


def _partition_day(partition_id: str) -> datetime:
    try:
        d = date.fromisoformat(partition_id)
    except ValueError:
        d = EPOCH
    return datetime(d.year, d.month, d.day)


class SimulatedCustomerSource:
    def __init__(self, scenario: Scenario = Scenario.HEALTHY, rows: int = 500, seed: int = 42,
                 name: str = "simulated:customers") -> None:
        self.scenario = scenario
        self.rows = rows
        self.seed = seed
        self.name = name

    def _healthy_rows(self, partition_id: str) -> list[dict[str, Any]]:
        rng = random.Random(f"{self.seed}:{partition_id}")
        base = _partition_base(partition_id, self.rows)
        day = _partition_day(partition_id)
        out = []
        for i in range(self.rows):
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            cid = base + i
            age = int(min(90, max(18, rng.gauss(38, 11))))
            created = day + timedelta(seconds=rng.randrange(86_400))
            out.append({
                "customer_id": cid,
                "name": f"{first} {last}",
                "age": age if rng.random() > 0.02 else None,
                "email": f"{first}.{last}{cid}@{rng.choice(DOMAINS)}".lower(),
                "created_at": created.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        return out

    def build_payload(self, partition_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        schema = {k: dict(v) for k, v in BASE_SCHEMA.items()}
        records = self._healthy_rows(partition_id)
        rng = random.Random(f"{self.seed}:{partition_id}:{self.scenario}")
        s = self.scenario

        if s == Scenario.TYPE_DRIFT:
            for spec in schema.values():
                spec["type"] = DataType.STRING
            for r in records:
                for k, v in r.items():
                    if k == "created_at":
                        r[k] = v.replace("T", " ")
                    elif v is not None:
                        r[k] = str(v)
        elif s == Scenario.DATE_FORMAT_DRIFT:
            schema["created_at"]["type"] = DataType.STRING
            for r in records:
                r["created_at"] = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%S").strftime("%d/%m/%Y %H:%M:%S")
        elif s == Scenario.INVALID_VALUES:
            schema["customer_id"].update(type=DataType.STRING, nullable=True)
            bad_idx = set(rng.sample(range(len(records)), k=max(3, len(records) // 40)))
            for i, r in enumerate(records):
                r["customer_id"] = (rng.choice(INVALID_IDS + [None]) if i in bad_idx else str(r["customer_id"]))
        elif s == Scenario.NEW_COLUMN:
            schema["phone_number"] = {"type": DataType.STRING, "nullable": True}
            for r in records:
                r["phone_number"] = f"+1-555-{rng.randrange(1000, 9999)}" if rng.random() > 0.1 else None
        elif s == Scenario.SEMANTIC_DRIFT:
            # upstream silently replaced exact age with an age-band code (1..6):
            # same type, still inside the contract's valid range, different meaning
            bands = [(24, 1), (34, 2), (44, 3), (54, 4), (64, 5)]
            for r in records:
                if r["age"] is not None:
                    r["age"] = next((code for limit, code in bands if r["age"] <= limit), 6)
        elif s == Scenario.COLUMN_RENAME:
            schema["email_address"] = schema.pop("email")
            for r in records:
                r["email_address"] = r.pop("email")
        elif s == Scenario.COLUMN_REMOVED:
            schema.pop("age")
            for r in records:
                r.pop("age")
        elif s == Scenario.NULLABILITY_CHANGE:
            schema["email"]["nullable"] = True
            for r in records:
                if rng.random() < 0.05:
                    r["email"] = None
        elif s == Scenario.DUPLICATES:
            for i in rng.sample(range(1, len(records)), k=len(records) // 50):
                records[i]["customer_id"] = records[i - 1]["customer_id"]

        declared = {"fields": {k: {**v, "type": str(v["type"])} for k, v in schema.items()}}
        return declared, records

    def fetch(self, partition_id: str) -> SourceBatch:
        validate_partition_id(partition_id)
        if self.scenario == Scenario.MISSING_PARTITION:
            raise PartitionNotFound(f"upstream has no data for partition {partition_id}")
        declared, records = self.build_payload(partition_id)
        raw = json.dumps({"schema": declared, "records": records})
        if self.scenario == Scenario.MALFORMED_JSON:
            raw = raw[: len(raw) // 2]  # producer crashed mid-write
        return parse_envelope(self.name, partition_id, raw)
