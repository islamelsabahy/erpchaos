from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from erpchaos.events import BusinessEvent


class EffectDefinition(BaseModel):
    """Map event types to signed integer contributions for one business effect."""

    model_config = ConfigDict(extra="forbid")

    contributions: dict[str, int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contributions(self) -> EffectDefinition:
        for event_type, delta in self.contributions.items():
            if not event_type.strip():
                raise ValueError("effect contribution event types must not be empty")
            if delta == 0:
                raise ValueError("effect contributions must be non-zero integers")
        return self


class EffectMap(BaseModel):
    """Declarative vendor-neutral business-effect projection configuration."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["erpchaos.effect-map.v1"] = Field(alias="schema")
    name: str = Field(min_length=1)
    effects: dict[str, EffectDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_effect_names(self) -> EffectMap:
        for effect_name in self.effects:
            if not effect_name.strip():
                raise ValueError("effect names must not be empty")
        return self


def project_effect_ledger(
    events: list[BusinessEvent],
    effect_map: EffectMap,
) -> dict[str, object]:
    """Project ordered events into deterministic net business-effect balances."""

    projected: dict[str, dict[str, int | bool]] = {}

    for effect_name, definition in effect_map.effects.items():
        balance = 0
        min_balance = 0
        max_balance = 0
        contribution_count = 0

        for event in events:
            delta = definition.contributions.get(event.event_type)
            if delta is None:
                continue

            balance += delta
            contribution_count += 1
            min_balance = min(min_balance, balance)
            max_balance = max(max_balance, balance)

        projected[effect_name] = {
            "balance": balance,
            "min_balance": min_balance,
            "max_balance": max_balance,
            "contribution_count": contribution_count,
            "ever_negative": min_balance < 0,
        }

    return {"effects": projected}
