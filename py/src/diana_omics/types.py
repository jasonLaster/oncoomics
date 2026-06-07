from __future__ import annotations

from typing import Any, Callable, TypedDict, Union

JsonScalar = Union[str, int, float, bool, None]
JsonValue = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]
CsvRow = dict[str, str]
JsonObject = dict[str, Any]
Command = Callable[[], None]


class FastqRecord(TypedDict):
    id: str
    sequence: str
    quality: str


class FastqStats(TypedDict):
    run: str
    read: str
    sourceUrl: str
    outputPath: str
    records: int
    minLength: int
    maxLength: int
    meanLength: float
    gcFraction: float
    nFraction: float
    qualityAsciiMin: int
    qualityAsciiMax: int
    firstReadId: str
    lastReadId: str
    ids: list[str]


class ToolRecord(TypedDict):
    tool: str
    path: str
    available: bool


class ToolGroup(TypedDict):
    group: str
    requiredFor: str
    tools: list[ToolRecord]
    allAvailable: bool


def as_str(value: object) -> str:
    return "" if value is None else str(value)
