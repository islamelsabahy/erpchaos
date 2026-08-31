from erpchaos.events import BusinessEvent, EventStream
from erpchaos.faults import ChaosScenario, FaultSpec, FaultType
from erpchaos.replay import replay


def test_replay_applies_faults_in_declared_order() -> None:
    stream = EventStream(
        transaction_id="tx-1",
        events=[
            BusinessEvent(event_id="reservation", event_type="reservation.created"),
            BusinessEvent(event_id="payment", event_type="payment.received"),
            BusinessEvent(event_id="contract", event_type="contract.generated"),
        ],
    )
    scenario = ChaosScenario(
        name="duplicate-then-drop-contract",
        faults=[
            FaultSpec(type=FaultType.duplicate_event, target_event_id="payment"),
            FaultSpec(type=FaultType.drop_event, target_event_id="contract"),
        ],
    )

    result = replay(stream, scenario)

    assert result.changed is True
    assert [event.event_id for event in result.original_events] == [
        "reservation",
        "payment",
        "contract",
    ]
    assert [event.event_id for event in result.mutated_events] == [
        "reservation",
        "payment",
        "payment#dup1",
    ]
