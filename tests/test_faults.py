from erpchaos.events import BusinessEvent
from erpchaos.faults import FaultSpec, FaultType, apply_fault


def _events() -> list[BusinessEvent]:
    return [
        BusinessEvent(event_id="a", event_type="a"),
        BusinessEvent(event_id="b", event_type="b"),
        BusinessEvent(event_id="c", event_type="c"),
        BusinessEvent(event_id="d", event_type="d"),
    ]


def test_duplicate_event() -> None:
    result = apply_fault(
        _events(),
        FaultSpec(type=FaultType.duplicate_event, target_event_id="b", repeat=2),
    )
    assert [event.event_id for event in result] == ["a", "b", "b#dup1", "b#dup2", "c", "d"]


def test_drop_event() -> None:
    result = apply_fault(
        _events(),
        FaultSpec(type=FaultType.drop_event, target_event_id="b"),
    )
    assert [event.event_id for event in result] == ["a", "c", "d"]


def test_delay_event() -> None:
    result = apply_fault(
        _events(),
        FaultSpec(type=FaultType.delay_event, target_event_id="b", positions=2),
    )
    assert [event.event_id for event in result] == ["a", "c", "d", "b"]


def test_reorder_event() -> None:
    result = apply_fault(
        _events(),
        FaultSpec(type=FaultType.reorder_event, target_event_id="c", positions=2),
    )
    assert [event.event_id for event in result] == ["c", "a", "b", "d"]


def test_partial_failure_truncates_after_target() -> None:
    result = apply_fault(
        _events(),
        FaultSpec(type=FaultType.partial_failure, target_event_id="b"),
    )
    assert [event.event_id for event in result] == ["a", "b"]
