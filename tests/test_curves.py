"""Analytic identities and adversarial shapes for the exact timing algebra."""

from fractions import Fraction
from random import Random

import pytest

from dagcert.curves import Curve, CurveError


def test_decimal_input_is_exact_and_collinear_points_are_removed() -> None:
    curve = Curve.from_points([(0, "0.1"), (1, 0.3), (2, "0.5")], "0.2")
    assert curve.points == ((Fraction(0), Fraction(1, 10)),)
    assert curve.value("3.5") == Fraction(4, 5)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "-inf", "1/0", True])
def test_nonfinite_and_boolean_input_is_rejected(bad: object) -> None:
    with pytest.raises(CurveError):
        Curve.from_points([(0, bad)])  # type: ignore[list-item]


@pytest.mark.parametrize("points", [[], [(1, 0)], [(0, 1), (0, 2)], [(0, 0), (-1, 0)]])
def test_malformed_domains_are_rejected(points: list[tuple[int, int]]) -> None:
    with pytest.raises(CurveError):
        Curve.from_points(points)


def test_arithmetic_uses_union_of_knots_and_preserves_negative_values() -> None:
    supply = Curve.from_points([(0, 0), (2, 0)], 3)
    demand = Curve.from_points([(0, 0), (1, 2)], 1)
    balance = Curve.constant(4).add(supply).sub(demand)
    assert balance.value(0) == 4
    assert balance.value(1) == 2
    assert balance.value(2) == 1
    assert balance.value(3) == 3
    assert balance.infimum() == 1
    assert balance.scale(-2).value(2) == -2


def test_minimum_and_maximum_find_crossings_between_declared_points() -> None:
    rising = Curve.from_points([(0, 0)], 3)
    falling = Curve.from_points([(0, 5)], -1)
    lower, upper = rising.minimum(falling), rising.maximum(falling)
    crossing = Fraction(5, 4)
    assert lower.points == ((Fraction(0), Fraction(0)), (crossing, Fraction(15, 4)))
    assert upper.points == ((Fraction(0), Fraction(5)), (crossing, Fraction(15, 4)))
    assert lower.tail_slope == -1
    assert upper.tail_slope == 3
    assert upper.infimum() == Fraction(15, 4)


def test_shift_retains_initial_value_and_shifts_every_breakpoint() -> None:
    original = Curve.from_points([(0, 2), (1, 4)], 1)
    shifted = original.shift("1.5")
    assert shifted.value(0) == 2
    assert shifted.value(1) == 2
    assert shifted.value(2) == 3
    assert shifted.value(3) == Fraction(9, 2)
    assert original.shift(0) is original
    with pytest.raises(CurveError, match="nonnegative"):
        original.shift(-1)


def test_extrema_check_interior_breakpoints_and_unbounded_tail() -> None:
    curve = Curve.from_points([(0, 2), (2, -3), (4, 6)], -1)
    assert curve.infimum(0, 4) == -3
    assert curve.supremum(1) == 6
    assert curve.infimum(3, 4) == Fraction(3, 2)
    assert curve.supremum(7) == 3
    assert curve.infimum(3, 3) == Fraction(3, 2)
    with pytest.raises(CurveError, match="unbounded below"):
        curve.infimum()
    with pytest.raises(CurveError, match="unbounded above"):
        curve.scale(-1).supremum()
    with pytest.raises(CurveError, match="start <= end"):
        curve.infimum(4, 3)
    with pytest.raises(CurveError, match="nonnegative"):
        curve.value(-1)


@pytest.mark.parametrize("left_rate,right_rate", [(3, 5), (5, 3), (4, 4)])
def test_convolution_of_rate_latency_services(left_rate: int, right_rate: int) -> None:
    left = Curve.from_points([(0, 0), (2, 0)], left_rate)
    right = Curve.from_points([(0, 0), (3, 0)], right_rate)
    expected = Curve.from_points([(0, 0), (5, 0)], min(left_rate, right_rate))
    assert left.convolution(right) == expected
    assert right.convolution(left) == expected


@pytest.mark.parametrize("service_rate", [3, 5])
def test_deconvolution_of_affine_arrival_and_rate_latency_service(service_rate: int) -> None:
    arrival = Curve.from_points([(0, 7)], 3)
    service = Curve.from_points([(0, 0), (2, 0)], service_rate)
    assert arrival.deconvolution(service) == Curve.from_points([(0, 13)], 3)


def test_deconvolution_refuses_unbounded_backlog_without_sampling_a_horizon() -> None:
    arrival = Curve.from_points([(0, 0)], 4)
    service = Curve.from_points([(0, 0), (1_000_000, 0)], 3)
    with pytest.raises(CurveError, match="unbounded above"):
        arrival.deconvolution(service)


def test_nonconvex_convolution_and_deconvolution_match_exact_fixed_time_extrema() -> None:
    # Test varying slopes and signed values, not only the convex service curves
    # and concave arrival curves used in elementary calculus examples.
    random = Random(491)
    for _ in range(12):
        left = Curve.from_points([(time, random.randint(-5, 9)) for time in range(4)], 1)
        right = Curve.from_points([(time, random.randint(-5, 9)) for time in range(4)], 2)
        convolved = left.convolution(right)
        deconvolved = left.deconvolution(right)
        for numerator in range(49):
            time = Fraction(numerator, 7)
            # At a fixed t the continuous piecewise-affine objective can attain
            # an extremum only at the interval endpoints or an operand's knot.
            splits = {Fraction(0), time}
            splits.update(knot for knot, _ in left.points if knot <= time)
            splits.update(time - knot for knot, _ in right.points if knot <= time)
            expected_minimum = min(left.value(split) + right.value(time - split) for split in splits)
            assert convolved.value(time) == expected_minimum
            offsets = {Fraction(0)}
            offsets.update(knot for knot, _ in right.points)
            offsets.update(knot - time for knot, _ in left.points if knot >= time)
            expected_maximum = max(left.value(time + offset) - right.value(offset) for offset in offsets)
            assert deconvolved.value(time) == expected_maximum


def test_convolution_associativity_on_nonconvex_curves() -> None:
    first = Curve.from_points([(0, 0), (1, 3), (2, 4)], 2)
    second = Curve.from_points([(0, 0), (2, 1), (3, 7)], 1)
    third = Curve.from_points([(0, 0), (1, 0)], 4)
    assert first.convolution(second).convolution(third) == first.convolution(second.convolution(third))


def test_extremum_can_depend_on_an_arbitrarily_late_intersection() -> None:
    reserve = Curve.from_points([(0, 50)], "0.000000001")
    drain = Curve.from_points([(0, 100)], "-0.000000001")
    combined = reserve.minimum(drain)
    assert combined.supremum() == 75
    assert combined.value(25_000_000_000) == 75
