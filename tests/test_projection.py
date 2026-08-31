from erpchaos.events import BusinessEvent
from erpchaos.projection import project_event_history


def test_project_event_history_counts_and_positions() -> None:
    events = [
        BusinessEvent(event_id="1", event_type="payment.received"),
        BusinessEvent(event_id="2", event_type="contract.generated"),
        BusinessEvent(event_id="3", event_type="payment.received"),
    ]

    state = project_event_history(events)

    assert state["history"]["event_count"] == 3
    assert state["history"]["sequence"] == [
        "payment_received",
        "contract_generated",
        "payment_received",
    ]
    assert state["history"]["types"]["payment_received"] == {
        "count": 2,
        "first_position": 1,
        "last_position": 3,
    }
