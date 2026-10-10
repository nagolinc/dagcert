from fractions import Fraction

import pytest

from dagcert.curves import Curve
from dagcert.scheduling import (
    SchedulingError,
    batch_work_demand,
    leftover_service,
    reserved_services,
    with_batch_flush_delay,
)


def rate(value: int | str) -> Curve:
    return Curve.from_points([(0, 0)], value)


def test_two_flows_can_share_one_server_with_positive_service() -> None:
    server = rate(1)
    interactive_demand = Curve.from_points([(0, 10)], "1/4")
    background_demand = Curve.from_points([(0, 20)], "1/2")
    interactive = leftover_service(server, background_demand)
    background = leftover_service(server, interactive_demand)
    assert interactive.value(100) == 30
    assert background.value(100) == 65
    assert interactive.tail_slope == Fraction(1, 2)
    assert background.tail_slope == Fraction(3, 4)
    # These are demand-dependent individual guarantees, not two reservations
    # whose slopes can be added to assert more than one server's capacity.


def test_nonpreemptible_background_work_invalidates_short_deadline() -> None:
    server = rate(1)  # GPU-work milliseconds per elapsed millisecond.
    no_higher_priority_work = Curve.constant(0)
    interactive = leftover_service(server, no_higher_priority_work, blocking_work=2000)
    assert interactive.value(100) == 0  # A 100 ms request deadline is not proved.
    assert interactive.value(2000) == 0
    assert interactive.value(2010) == 10
    assert leftover_service(server, no_higher_priority_work).value(100) == 100


def test_bursty_priority_demand_is_not_replaced_by_average() -> None:
    busy = leftover_service(rate(1), Curve.from_points([(0, 2000)], "1/4"))
    average_only = leftover_service(rate(1), rate("1/4"))
    assert busy.value(100) == 0
    assert average_only.value(100) == 75
    assert busy.value(4000) == 1000


def test_leftover_exact_rational_latency() -> None:
    service = leftover_service(rate("3/2"), Curve.from_points([(0, "1/3")], "1/2"))
    assert service.points == ((Fraction(0), Fraction(0)), (Fraction(1, 3), Fraction(0)))
    assert service.value("4/3") == 1


def test_nonmonotone_residual_uses_conservative_increasing_minorant() -> None:
    # Raw residual rises to 3, falls to 1, then grows again. Its early peak is
    # not silently promoted to a strict-service guarantee.
    server = Curve.from_points([(0, 0), (1, 3), (2, 3), (3, 7)], 1)
    cross = Curve.from_points([(0, 0), (1, 0), (2, 2)], 0)
    service = leftover_service(server, cross)
    assert service.value("1/3") == 1
    assert service.value(1) == 1
    assert service.value(2) == 1
    assert service.value(3) == 5
    raw = server.sub(cross)
    assert service.sub(raw).supremum() <= 0


def test_overload_and_later_overload_yield_no_persistent_service() -> None:
    assert leftover_service(rate(1), rate(2)) == Curve.constant(0)
    initially_idle_cross = Curve.from_points([(0, 0), (10, 0)], 2)
    assert leftover_service(rate(1), initially_idle_cross) == Curve.constant(0)


def test_reserved_service_accounts_for_shared_capacity_and_packet_lag() -> None:
    service = reserved_services(
        rate(1), {"interactive": "3/5", "background": "2/5"},
        service_lag_work={"interactive": 20},
    )
    assert service["interactive"].value(100) == 40
    assert service["background"].value(100) == 40
    assert service["interactive"].add(service["background"]).value(100) <= 100


def test_reserved_services_do_not_silently_normalize_overcommit() -> None:
    with pytest.raises(SchedulingError, match="exceed"):
        reserved_services(rate(1), {"one": "3/4", "two": "3/4"})


def test_unused_reservation_capacity_is_not_promised() -> None:
    services = reserved_services(rate(2), {"only": "1/4", "disabled": 0})
    assert services["only"].value(10) == 5
    assert services["disabled"] == Curve.constant(0)


def test_batch_work_includes_release_jitter_and_partial_batch_overhead() -> None:
    # Any t-wide release window may include quantity accumulated during the
    # previous 10 ms as well, plus a full overhead for each partial batch.
    quantity = Curve.from_points([(0, 2)], "1/2")
    batches = Curve.from_points([(0, 1)], "1/10")
    work = batch_work_demand(
        quantity, batches, work_per_unit_upper=3,
        overhead_per_batch_upper=4, flush_delay_upper=10,
    )
    assert work.value(0) == 25
    assert work.value(20) == 63
    assert work.tail_slope == Fraction(19, 10)


def test_batch_advance_preserves_shifted_knots_exactly() -> None:
    quantity = Curve.from_points([(0, 1), (10, 2), (20, 5)], 0)
    work = batch_work_demand(
        quantity, Curve.constant(0), work_per_unit_upper=1,
        overhead_per_batch_upper=0, flush_delay_upper=5,
    )
    assert work.value(0) == Fraction(3, 2)
    assert work.value(5) == 2
    assert work.value(15) == 5


def test_lone_request_flushes_without_another_arrival() -> None:
    service = with_batch_flush_delay(rate(1), maximum_wait=25)
    assert service.value(25) == 0
    assert service.value(35) == 10
    assert service.value(100) >= 10  # 10 work units meet a 100 ms deadline.
    assert with_batch_flush_delay(rate(1), 100).value(100) == 0


@pytest.mark.parametrize("curve", [
    Curve.from_points([(0, -1)], 1),
    Curve.from_points([(0, 0), (1, 2), (2, 1)], 1),
    Curve.from_points([(0, 0)], -1),
])
def test_malformed_demand_rejected(curve: Curve) -> None:
    with pytest.raises(SchedulingError, match="nonnegative and nondecreasing"):
        leftover_service(rate(1), curve)


def test_service_must_start_at_zero() -> None:
    with pytest.raises(SchedulingError, match="start at zero"):
        leftover_service(Curve.from_points([(0, 1)], 1), Curve.constant(0))


@pytest.mark.parametrize("blocking", [-1, "-1/4"])
def test_negative_blocking_rejected(blocking: int | str) -> None:
    with pytest.raises(SchedulingError, match="nonnegative"):
        leftover_service(rate(1), Curve.constant(0), blocking_work=blocking)


def test_reservation_names_and_lags_checked() -> None:
    with pytest.raises(SchedulingError, match="at least one"):
        reserved_services(rate(1), {})
    with pytest.raises(SchedulingError, match="nonempty"):
        reserved_services(rate(1), {"": 1})
    with pytest.raises(SchedulingError, match="nonnegative"):
        reserved_services(rate(1), {"one": -1})
    with pytest.raises(SchedulingError, match="identify declared"):
        reserved_services(rate(1), {"one": 1}, service_lag_work={"missing": 1})
    with pytest.raises(SchedulingError, match="nonnegative"):
        reserved_services(rate(1), {"one": 1}, service_lag_work={"one": -1})


def test_negative_batch_premises_rejected() -> None:
    with pytest.raises(SchedulingError, match="nonnegative"):
        batch_work_demand(rate(1), rate(1), work_per_unit_upper=-1, overhead_per_batch_upper=0)
    with pytest.raises(SchedulingError, match="nonnegative"):
        batch_work_demand(rate(1), rate(1), work_per_unit_upper=1, overhead_per_batch_upper=-1)
    with pytest.raises(SchedulingError, match="nonnegative"):
        batch_work_demand(
            rate(1), rate(1), work_per_unit_upper=1,
            overhead_per_batch_upper=0, flush_delay_upper=-1,
        )
    with pytest.raises(SchedulingError, match="nonnegative"):
        with_batch_flush_delay(rate(1), -1)
