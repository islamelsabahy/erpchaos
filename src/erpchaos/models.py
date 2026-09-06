from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Operator(StrEnum):
    equals = "equals"
    not_equals = "not_equals"
    lte = "lte"
    gte = "gte"
    before = "before"
    after = "after"


class Invariant(BaseModel):
    name: str
    description: str | None = None
    path: str
    operator: Operator = Operator.equals
    expected: Any = None
    expected_path: str | None = None
    severity: Severity = Severity.high

    @model_validator(mode="after")
    def validate_comparison(self) -> Invariant:
        if self.operator in {Operator.before, Operator.after} and not self.expected_path:
            raise ValueError(f"{self.operator.value} requires expected_path")
        return self


class BusinessReliabilityContract(BaseModel):
    name: str
    version: str = "1"
    transaction: str
    description: str | None = None
    invariants: list[Invariant] = Field(min_length=1)
