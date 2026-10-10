"""Exact workload service bounds for shared workers and bounded-wait batching.

The functions derive curves, not scheduler correctness. A certificate must bind
the aggregate strict service, interval demand, scheduling policy, and any
blocking/lag bound to the actual production system. In particular, an ordinary
service curve is not interchangeable with an aggregate *strict* service curve.

The leftover rule is the conservative form of Le Boudec and Thiran, Network
Calculus, Theorem 6.2.1 and its nonpreemptive priority corollary:
https://leboudec.github.io/netcal/latex/netCalBook.pdf . All quantities use the
same work unit; time can use any one consistent unit. No rates are inferred
from samples, nominal worker counts, or average scheduler weights.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

from .curves import Curve, CurveError, Scalar, _rational


class SchedulingError(CurveError):
    """Scheduling premises are malformed or incompatible."""


def _nonnegative(value: Scalar, name: str) -> Fraction:
    result = _rational(value)
    if result < 0:
        raise SchedulingError(f"{name} must be nonnegative")
    return result


def _increasing(curve: Curve, name: str, *, starts_at_zero: bool = False) -> None:
    if curve.points[0][1] < 0 or curve.tail_slope < 0:
        raise SchedulingError(f"{name} must be nonnegative and nondecreasing")
    if any(left[1] > right[1] for left, right in zip(curve.points, curve.points[1:])):
        raise SchedulingError(f"{name} must be nonnegative and nondecreasing")
    if starts_at_zero and curve.points[0][1] != 0:
        raise SchedulingError(f"{name} must start at zero")


def _monotone_minorant(curve: Curve) -> Curve:
    """Return the exact greatest nondecreasing minorant inf_{u >= t} curve(u).

    Callers first clamp to zero, so the final slope is nonnegative. Keeping
    below the raw residual avoids upgrading a nonmonotone lower bound without
    a separate theorem. Dips in future service therefore remain conservative.
    """
    if curve.tail_slope < 0:
        raise SchedulingError("a service minorant cannot have a negative infinite tail")
    future_min = curve.points[-1][1]
    points = [curve.points[-1]]
    for (left_time, left_value), (right_time, right_value) in reversed(
        list(zip(curve.points, curve.points[1:]))
    ):
        if left_value < future_min < right_value:
            slope = (right_value - left_value) / (right_time - left_time)
            crossing = left_time + (future_min - left_value) / slope
            points.append((crossing, future_min))
        future_min = min(future_min, left_value)
        points.append((left_time, future_min))
    return Curve(tuple(reversed(points)), curve.tail_slope)


def leftover_service(
    total_strict_service: Curve,
    cross_interval_demand: Curve,
    *,
    blocking_work: Scalar = 0,
) -> Curve:
    """Derive an ordinary service curve after competing work and blocking.

    ``total_strict_service(t)`` bounds work provided over every continuously
    backlogged interval of length t. ``cross_interval_demand(t)`` bounds ALL
    competing work arriving in EVERY interval of length t, not just cumulative
    arrivals since process startup. Include initial competing backlog in its
    burst allowance. Include retry attempts and per-batch overhead in work.

    Under arbitrary multiplexing, cross demand includes every other class.
    Under strict priority, it includes higher-priority classes; separately,
    ``blocking_work`` bounds the lower-priority nonpreemptible work already
    executing when the target becomes backlogged. Excluding lower-priority
    traffic requires the production scheduler to enforce that priority rule.

    The result is a nondecreasing minorant of [beta - alpha - blocking]+.
    Overload yields zero service, never a manufactured finite delay. The result
    must NOT be fed back as ``total_strict_service`` without a strictness proof.
    """
    _increasing(total_strict_service, "total strict service", starts_at_zero=True)
    _increasing(cross_interval_demand, "cross interval demand")
    blocking = _nonnegative(blocking_work, "nonpreemptible blocking work")
    raw = total_strict_service.sub(cross_interval_demand).sub(Curve.constant(blocking))
    return _monotone_minorant(raw.maximum(Curve.constant(0)))


def reserved_services(
    total_strict_service: Curve,
    shares: Mapping[str, Scalar],
    *,
    service_lag_work: Mapping[str, Scalar] | None = None,
) -> dict[str, Curve]:
    """Derive simultaneously feasible service reservations from one worker.

    The scheduler must guarantee each continuously backlogged class at least
    its declared fraction of aggregate strict service, minus its declared
    bounded work lag. An ideal fluid GPS scheduler has lag zero; a packet/job
    implementation needs a separately justified lag, including nonpreemptible
    blocking. Configured weights or a long-run average share alone do NOT
    establish this premise. Unused capacity may be borrowed, but is not promised.

    Shares are absolute fractions of this same server, not weights silently
    normalized to fit. Their sum must be at most one. This permits overlapping
    tasks sharing one worker without claiming each task owns an entire worker.
    """
    _increasing(total_strict_service, "total strict service", starts_at_zero=True)
    if not shares:
        raise SchedulingError("service reservations must contain at least one class")
    if any(not isinstance(name, str) or not name for name in shares):
        raise SchedulingError("service reservation names must be nonempty strings")
    fractions = {name: _nonnegative(share, f"share for {name}") for name, share in shares.items()}
    if sum(fractions.values(), Fraction(0)) > 1:
        raise SchedulingError("service reservations exceed the shared server capacity")
    lags = {} if service_lag_work is None else dict(service_lag_work)
    if set(lags) - set(shares):
        raise SchedulingError("service lag names must identify declared reservations")
    return {
        name: total_strict_service.scale(share).sub(Curve.constant(
            _nonnegative(lags.get(name, 0), f"service lag for {name}"),
        )).maximum(Curve.constant(0))
        for name, share in fractions.items()
    }


def _advance(curve: Curve, amount: Fraction) -> Curve:
    """Exact curve(t + amount), including the shifted affine tail."""
    return Curve(
        ((Fraction(0), curve.value(amount)),)
        + tuple((time - amount, value) for time, value in curve.points if time > amount),
        curve.tail_slope,
    )


def batch_work_demand(
    input_quantity_upper: Curve,
    batch_count_upper: Curve,
    *,
    work_per_unit_upper: Scalar,
    overhead_per_batch_upper: Scalar,
    flush_delay_upper: Scalar = 0,
) -> Curve:
    """Bound work released by variable-sized, possibly partial batches.

    The input curve bounds quantity arriving in any interval. Each quantity
    unit enters at most one released batch, within ``flush_delay_upper`` of
    arrival; batches cannot invent or duplicate units. Release in an interval
    of length t can collect arrivals over t + flush_delay_upper. Initial queued
    units must be represented by the input burst or excluded by the epoch.

    ``batch_count_upper`` independently bounds batch RELEASES in any interval.
    It must include partial/timer-flushed batches. Dividing item count by a
    configured maximum batch size is NOT a sound batch-count upper bound.
    The per-unit cost plus per-batch overhead bounds every actual batch's work.
    Retries require their own demand; this operation does not count duplicates
    as useful output. Nonlinear cost can use any valid linear upper envelope.
    """
    _increasing(input_quantity_upper, "input interval quantity")
    _increasing(batch_count_upper, "interval batch release count")
    unit_cost = _nonnegative(work_per_unit_upper, "work per input unit")
    overhead = _nonnegative(overhead_per_batch_upper, "work per batch")
    delay = _nonnegative(flush_delay_upper, "batch flush delay")
    return _advance(input_quantity_upper, delay).scale(unit_cost).add(
        batch_count_upper.scale(overhead),
    )


def with_batch_flush_delay(service: Curve, maximum_wait: Scalar) -> Curve:
    """Compose a bounded-wait batch release stage with downstream service.

    Every input item must be released within the stated wait, including a lone
    item in a partial batch. A timer that only runs when another item arrives
    does not establish this premise. No batch-fill rate assumption is needed.
    The downstream service curve must count the same conserved work/quantity;
    variable batch cost first needs the separate workload transformation.
    """
    _increasing(service, "downstream service", starts_at_zero=True)
    return service.shift(_nonnegative(maximum_wait, "maximum batch wait"))
