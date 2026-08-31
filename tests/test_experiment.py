from erpchaos.events import BusinessEvent, EventStream
from erpchaos.experiment import run_experiment
from erpchaos.faults import ChaosScenario, FaultSpec, FaultType
from erpchaos.models import BusinessReliabilityContract, Invariant, Severity


def test_duplicate_payment_experiment_breaks_idempotency() -> None:
    contract = BusinessReliabilityContract(
        name="payment reliability",
        transaction="property-sale-event-history",
        invariants=[
            Invariant(
                name="payment-idempotency",
                path="history.types.payment_received.count",
                operator="equals",
                expected=1,
                severity=Severity.critical,
            )
        ],
    )
    stream = EventStream(
        transaction_id="tx-1",
        events=[
            BusinessEvent(event_id="reservation", event_type="reservation.created"),
            BusinessEvent(event_id="payment", event_type="payment.received"),
        ],
    )
    scenario = ChaosScenario(
        name="duplicate-payment",
        faults=[
            FaultSpec(type=FaultType.duplicate_event, target_event_id="payment"),
        ],
    )

    result = run_experiment(contract, scenario, stream)

    assert result.passed is False
    assert result.score == 0
    assert result.invariant_results[0].actual == 2
