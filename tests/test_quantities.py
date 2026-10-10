"""Behavioral tests for variable-sized cumulative work and useful output."""

from fractions import Fraction
from random import Random

import pytest

from dagcert.curves import Curve
from dagcert.quantities import (
    QuantityBounds,
    QuantityError,
    compose_monotone,
    ordered_prefix_lower,
    quantity_bounds,
    quantity_service,
    running_maximum,
)


def test_composition_finds_crossings_not_present_in_either_time_grid() -> None:
    inner = Curve.from_points([(0, 1), (2, 5)], 1)
    outer = Curve.from_points([(0, 0), (2, 1), (4, 7)], 2)
    result = compose_monotone(outer, inner)
    assert result.points == (
        (Fraction(0), Fraction(1, 2)),
        (Fraction(1, 2), Fraction(1)),
        (Fraction(3, 2), Fraction(7)),
        (Fraction(2), Fraction(9)),
    )
    assert result.tail_slope == 2
    assert result.value(3) == 11


def test_composition_handles_plateaus_and_saturated_inner_curve() -> None:
    inner = Curve.from_points([(0, 0), (1, 2), (3, 2), (5, 4)])
    outer = Curve.from_points([(0, 0), (2, 8), (3, 9)], 3)
    result = compose_monotone(outer, inner)
    for numerator in range(41):
        time = Fraction(numerator, 5)
        assert result.value(time) == outer.value(inner.value(time))
    assert result.value(10000) == 12
    assert result.tail_slope == 0


def test_composition_handles_knots_only_reached_on_the_infinite_tail() -> None:
    result = compose_monotone(
        Curve.from_points([(0, 0), (100, 5)], 7),
        Curve.from_points([(0, 10)], 3),
    )
    assert result.value(30) == 5
    assert result.value(31) == 26
    assert result.tail_slope == 21


def test_composition_matches_direct_evaluation_for_varied_exact_shapes() -> None:
    random = Random(2718)
    for _ in range(30):
        curves = []
        for _ in range(2):
            value = random.randrange(4)
            points = []
            for time in range(5):
                points.append((time, value))
                value += random.randrange(4)
            curves.append(Curve.from_points(points, random.randrange(4)))
        outer, inner = curves
        result = compose_monotone(outer, inner)
        for numerator in range(75):
            time = Fraction(numerator, 7)
            assert result.value(time) == outer.value(inner.value(time))


@pytest.mark.parametrize(
    "bad",
    [Curve.constant(-1), Curve.from_points([(0, 2), (1, 1)]), Curve.from_points([(0, 0)], -1)],
)
def test_composition_refuses_negative_or_decreasing_operands(bad: Curve) -> None:
    with pytest.raises(QuantityError, match="nonnegative and nondecreasing"):
        compose_monotone(bad, Curve.constant(0))
    with pytest.raises(QuantityError, match="nonnegative and nondecreasing"):
        compose_monotone(Curve.constant(0), bad)


def test_count_to_quantity_retains_a_cumulative_variable_yield_relationship() -> None:
    # The lower relation is not a fixed minimum size times a task count.
    yields = Curve.from_points([(0, 0), (1, 1), (2, 5)], 2)
    result = quantity_bounds(
        Curve.from_points([(0, 0), (3, 0)], 1),
        Curve.from_points([(0, 1)], 1),
        yields,
        yields.add(Curve.constant(2)),
    )
    assert result.lower.value(4) == 1
    assert result.lower.value(5) == 5
    assert result.lower.value(6) == 7
    assert result.upper.value(1) == 7


def test_impossible_quantity_bounds_are_rejected_even_far_out_on_tail() -> None:
    with pytest.raises(QuantityError, match="lower exceeds"):
        QuantityBounds(Curve.from_points([(0, 0)], 2), Curve.from_points([(0, 100000)], 1))
    with pytest.raises(QuantityError, match="zero at zero"):
        quantity_bounds(Curve.constant(0), Curve.constant(1), Curve.constant(1), Curve.constant(2))


def test_nonproducing_outcomes_do_not_turn_completed_attempts_into_useful_output() -> None:
    attempts = Curve.from_points([(0, 0)], 100)
    result = quantity_bounds(
        attempts, attempts, Curve.constant(0), Curve.from_points([(0, 0)], 5),
    )
    assert result.lower == Curve.constant(0)
    assert result.upper.value(1) == 500


def test_aggregate_work_yields_realtime_service_despite_individual_slow_jobs() -> None:
    # Repeated jobs: produce 2 seconds in 3 worker-seconds, then 5 in 2.
    # Some jobs are slower than playback. Against cost coefficient 0.8,
    # their excesses are +1.4 and -2, so EVERY contiguous block has excess
    # <= 1.4 (a whole pair only lowers it). At most 3 work-seconds remain
    # in an unfinished job. These are declared interval hypotheses, not
    # statistical estimates inferred by quantity_service from samples.
    service = quantity_service(
        Curve.from_points([(0, 0)], 1),
        work_per_quantity="0.8",
        excess_work="1.4",
        unfinished_work=3,
    )
    assert service == Curve.from_points([(0, 0), ("4.4", 0)], "1.25")
    reserve = Curve.constant(5).add(service).sub(Curve.from_points([(0, 0)], 1))
    assert reserve.infimum() == Fraction(3, 5)
    # Using max job cost / min job yield loses this valid aggregate result.
    fixed_per_job_service = quantity_service(
        Curve.from_points([(0, 0)], 1), work_per_quantity="1.5", unfinished_work=3,
    )
    assert fixed_per_job_service.tail_slope < 1


def test_service_lower_never_exceeds_actual_alternating_chunk_completions() -> None:
    service = quantity_service(
        Curve.from_points([(0, 0)], 1),
        work_per_quantity="0.8", excess_work="1.4", unfinished_work=3,
    )
    for numerator in range(1000):
        time = Fraction(numerator, 10)
        pairs = int(time // 5)
        output = 7 * pairs + (2 if time - 5 * pairs >= 3 else 0)
        assert service.value(time) <= output


def test_slow_fast_service_relation_also_holds_away_from_the_initial_epoch() -> None:
    service = quantity_service(
        Curve.from_points([(0, 0)], 1),
        work_per_quantity="0.8", excess_work="1.4", unfinished_work=3,
    )

    def completed(time: Fraction) -> int:
        pairs = int(time // 5)
        return 7 * pairs + (2 if time - 5 * pairs >= 3 else 0)

    for start_numerator in range(40):
        start = Fraction(start_numerator, 7)
        for interval_numerator in range(80):
            duration = Fraction(interval_numerator, 7)
            assert service.value(duration) <= completed(start + duration) - completed(start)


@pytest.mark.parametrize("rate,burst,unfinished", [(0, 0, 0), (-1, 0, 0), (1, -1, 0), (1, 0, -1)])
def test_invalid_cost_relations_cannot_create_quantity_service(
    rate: int, burst: int, unfinished: int,
) -> None:
    with pytest.raises(QuantityError):
        quantity_service(
            Curve.from_points([(0, 0)], 1),
            work_per_quantity=rate, excess_work=burst, unfinished_work=unfinished,
        )


def test_initial_work_burst_is_not_silently_treated_as_interval_service() -> None:
    with pytest.raises(QuantityError, match="start at zero"):
        quantity_service(Curve.from_points([(0, 10)], 1), work_per_quantity=1)


def test_faster_long_run_rate_does_not_hide_a_reserve_exhausting_outage() -> None:
    service = quantity_service(
        Curve.from_points([(0, 0), (120, 0)], 2), work_per_quantity=1,
    )
    reserve = Curve.constant(60).add(service).sub(Curve.from_points([(0, 0)], 1))
    assert service.tail_slope > 1
    assert reserve.infimum() == -60


def test_ordered_prefix_accounts_for_total_stranded_quantity_not_one_gap() -> None:
    completed = Curve.from_points([(0, 0)], 5)
    assert ordered_prefix_lower(completed, completed) == Curve.constant(0)
    assert ordered_prefix_lower(completed, Curve.constant(10)) == Curve.from_points(
        [(0, 0), (2, 0)], 5,
    )


def test_ordered_cumulative_lower_never_forgets_already_proved_progress() -> None:
    completed = Curve.from_points([(0, 0)], 2)
    withheld = Curve.from_points([(0, 0), (2, 0), (3, 5)])
    ordered = ordered_prefix_lower(completed, withheld)
    assert ordered.value(2) == 4
    assert ordered.value(3) == 4
    assert ordered.value("4.5") == 4
    assert ordered.value(5) == 5


def test_withheld_stock_bound_can_fall_as_an_earlier_gap_is_repaired() -> None:
    completed = Curve.from_points([(0, 0)], 2)
    withheld = Curve.from_points([(0, 6), (3, 0)])
    ordered = ordered_prefix_lower(completed, withheld)
    assert ordered.value(1) == 0
    assert ordered.value(2) == 2
    assert ordered.value(3) == 6
    with pytest.raises(QuantityError, match="nonnegative"):
        ordered_prefix_lower(completed, Curve.from_points([(0, 2)], -1))


def test_running_maximum_handles_negative_segments_and_tail_recovery() -> None:
    original = Curve.from_points([(0, -3), (1, 5), (2, 2), (3, 7), (4, -2)], 3)
    upper = running_maximum(original)
    assert upper.value(0) == -3
    assert upper.value("1.5") == 5
    assert upper.value("2.5") == 5
    assert upper.value(7) == 7
    assert upper.value(8) == 10
    assert running_maximum(original.scale(-1)).tail_slope == 0


def test_running_maximum_matches_exact_prefix_extrema_on_varied_shapes() -> None:
    random = Random(31415)
    for _ in range(30):
        original = Curve.from_points(
            [(time, random.randrange(-10, 11)) for time in range(6)], random.randrange(-3, 4),
        )
        envelope = running_maximum(original)
        for numerator in range(100):
            time = Fraction(numerator, 7)
            assert envelope.value(time) == original.supremum(0, time)
