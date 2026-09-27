from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any


class DataType(StrEnum):
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"
    BOOLEAN = "BOOLEAN"
    TIMESTAMP = "TIMESTAMP"
    DATE = "DATE"
    JSON = "JSON"
    NULL = "NULL"

    @classmethod
    def parse(cls, raw: str) -> DataType:
        aliases = {
            "INT": cls.INTEGER, "BIGINT": cls.INTEGER, "LONG": cls.INTEGER,
            "DOUBLE": cls.FLOAT, "DECIMAL": cls.FLOAT, "NUMERIC": cls.FLOAT,
            "VARCHAR": cls.STRING, "TEXT": cls.STRING, "STR": cls.STRING,
            "BOOL": cls.BOOLEAN, "DATETIME": cls.TIMESTAMP,
        }
        key = raw.strip().upper()
        return aliases.get(key) or cls(key)


DUCKDB_TYPES: dict[DataType, str] = {
    DataType.INTEGER: "BIGINT",
    DataType.FLOAT: "DOUBLE",
    DataType.STRING: "VARCHAR",
    DataType.BOOLEAN: "BOOLEAN",
    DataType.TIMESTAMP: "TIMESTAMP",
    DataType.DATE: "DATE",
    DataType.JSON: "JSON",
    DataType.NULL: "VARCHAR",
}

_DUCKDB_TO_TYPE: dict[str, DataType] = {
    "BIGINT": DataType.INTEGER, "INTEGER": DataType.INTEGER, "HUGEINT": DataType.INTEGER,
    "SMALLINT": DataType.INTEGER, "TINYINT": DataType.INTEGER, "UBIGINT": DataType.INTEGER,
    "DOUBLE": DataType.FLOAT, "FLOAT": DataType.FLOAT, "REAL": DataType.FLOAT,
    "VARCHAR": DataType.STRING, "BOOLEAN": DataType.BOOLEAN,
    "TIMESTAMP": DataType.TIMESTAMP, "TIMESTAMP WITH TIME ZONE": DataType.TIMESTAMP,
    "DATE": DataType.DATE, "JSON": DataType.JSON,
}


def from_duckdb_type(duck: str) -> DataType:
    upper = duck.upper()
    if upper.startswith("DECIMAL"):
        return DataType.FLOAT
    return _DUCKDB_TO_TYPE.get(upper, DataType.STRING)


def physical_type(value: Any) -> DataType:
    if value is None:
        return DataType.NULL
    if isinstance(value, bool):
        return DataType.BOOLEAN
    if isinstance(value, int):
        return DataType.INTEGER
    if isinstance(value, float):
        return DataType.FLOAT
    if isinstance(value, datetime):
        return DataType.TIMESTAMP
    if isinstance(value, date):
        return DataType.DATE
    if isinstance(value, (dict, list)):
        return DataType.JSON
    return DataType.STRING


_WIDENINGS = {
    (DataType.INTEGER, DataType.FLOAT),
    (DataType.DATE, DataType.TIMESTAMP),
}


def is_widening(before: DataType, after: DataType) -> bool:
    return (before, after) in _WIDENINGS
