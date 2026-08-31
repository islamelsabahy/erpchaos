from __future__ import annotations

import re
from typing import Any

from erpchaos.effects import EffectMap, project_effect_ledger
from erpchaos.events import BusinessEvent
from erpchaos.lineage import EffectLineagePolicy, project_compensation_lineage


def _event_key(event_type: str) -> str:
    """Convert an event type into a stable path-safe projection key."""

    key = re.sub(r"[^a-zA-Z0-9]+", "_", event_type).strip("_").lower()
    if not key:
        raise ValueError("Event type cannot normalize to an empty key")
    return key


def project_event_history(events: list[BusinessEvent]) -> dict[str, Any]:
    """Project an ordered event stream into deterministic BRC-readable state."""

    counts: dict[str, int] = {}
    first_positions: dict[str, int] = {}
    last_positions: dict[str, int] = {}
    sequence: list[str] = []

    for position, event in enumerate(events, start=1):
        key = _event_key(event.event_type)
        sequence.append(key)
        counts[key] = counts.get(key, 0) + 1
        first_positions.setdefault(key, position)
        last_positions[key] = position

    event_types: dict[str, dict[str, int]] = {}
    for key, count in counts.items():
        event_types[key] = {
            "count": count,
            "first_position": first_positions[key],
            "last_position": last_positions[key],
        }

    return {
        "history": {
            "event_count": len(events),
            "sequence": sequence,
            "types": event_types,
        }
    }


def project_business_state(
    events: list[BusinessEvent],
    effect_map: EffectMap | None = None,
    lineage_policy: EffectLineagePolicy | None = None,
) -> dict[str, Any]:
    """Project history plus optional net effects and compensation lineage."""

    if lineage_policy is not None and effect_map is None:
        raise ValueError("lineage projection requires an effect map")

    state = project_event_history(events)
    if effect_map is not None:
        state["effects"] = project_effect_ledger(events, effect_map)["effects"]
    if lineage_policy is not None:
        assert effect_map is not None
        state["lineage"] = project_compensation_lineage(
            events,
            effect_map,
            lineage_policy,
        )["lineage"]
    return state
