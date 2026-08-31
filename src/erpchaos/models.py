from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Invariant(BaseModel):
    name: str
    description: str | None = None
    path: str
    operator: str = "equals"
    expected: Any
    severity: Severity = Severity.high


class BusinessReliabilityContract(BaseModel):
    name: str
    version: str = "1"
    transaction: str
    description: str | None = None
    invariants: list[Invariant] = Field(min_length=1)
