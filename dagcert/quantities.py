"""Exact quantity transforms for variable-sized work.

These functions are mathematical implications, not sources of premises. A
caller must bind the workload, yield, and ordering relations to the actual
typed production paths, scheduler, failures, and declared engineering
envelopes. In particular, observed average cost does not establish a bound
over every backlogged interval, and completed quantity is not automatically
ordered, unique, durable, or matched with another stream.

The argument of a :class:`Curve` here need not be time: it can be completed
invocation count, bytes, tokens, frames, or playable seconds. Units must agree
at composition boundaries; this module performs exact rational arithmetic,
not dimensional inference from field names.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction

from .curves import Curve, CurveError, Scalar, _rational


class QuantityError(CurveError):
    """A quantity relation does not satisfy the mathematical preconditions."""


def _nondecreasing(curve: Curve, name: str) -> None:
    if (
        curve.points[0][1] < 0
        or curve.tail_slope < 0
        or any(left[1] > right[1] for left, right in zip(curve.points, curve.points[1:]))
    ):
        raise QuantityError(f"{name} must be nonnegative and nondecreasing")


def _ordered(lower: Curve, upper: Curve, name: str) -> None:
    try:
        minimum = upper.sub(lower).infimum()
    except CurveError as error:
        raise QuantityError(f"{name} lower exceeds its upper bound") from error
    if minimum < 0:
        raise QuantityError(f"{name} lower exceeds its upper bound")


def compose_monotone(outer: Curve, inner: Curve) -> Curve:
    """Return ``outer(inner(t))`` exactly, including crossings between knots.

    Both operands must be nonnegative and nondecreasing. Constant segments
    and finite saturation are supported. This is ordinary function
    composition, not the min-plus convolution used to compose servers.
    """
    _nondecreasing(outer, "outer curve")
    _nondecreasing(inner, "inner curve")
    times = {time for time, _ in inner.points}
    values = tuple(value for _, value in inner.points)
    for knot, _ in outer.points:
        if knot < values[0]:
            continue
        index = bisect_right(values, knot) - 1
        start, value = inner.points[index]
        if index == len(inner.points) - 1:
            slope = inner.tail_slope
        else:
            end, next_value = inner.points[index + 1]
            slope = (next_value - value) / (end - start)
        if slope > 0:
            times.add(start + (knot - value) / slope)
    return Curve(
        tuple((time, outer.value(inner.value(time))) for time in sorted(times)),
        outer.tail_slope * inner.tail_slope,
    )


@dataclass(frozen=True, slots=True)
class QuantityBounds:
    """Lower and upper envelopes of the same cumulative useful quantity."""

    lower: Curve
    upper: Curve

    def __post_init__(self) -> None:
        _nondecreasing(self.lower, "quantity lower")
        _nondecreasing(self.upper, "quantity upper")
        _ordered(self.lower, self.upper, "quantity")


def quantity_bounds(
    completed_lower: Curve,
    completed_upper: Curve,
    yield_lower: Curve,
    yield_upper: Curve,
) -> QuantityBounds:
    """Map completed-count envelopes through cumulative yield relations.

    The premise is ``yield_lower(n) <= useful_yield(n) <= yield_upper(n)``
    for the actual completed sequence (and every relevant block if used as
    interval envelopes). It is not a promise about each invocation's size.
    Outcome filtering, duplicate removal, and failure yield belong in that
    premise. Fractional-count interpolation must itself be conservative;
    these helpers do not turn a few integer observations into an envelope.
    """
    QuantityBounds(completed_lower, completed_upper)
    QuantityBounds(yield_lower, yield_upper)
    if yield_lower.value(0) != 0:
        raise QuantityError("yield lower must be zero at zero completions")
    return QuantityBounds(
        compose_monotone(yield_lower, completed_lower),
        compose_monotone(yield_upper, completed_upper),
    )


def quantity_service(
    work_service: Curve,
    *,
    work_per_quantity: Scalar,
    excess_work: Scalar = 0,
    unfinished_work: Scalar = 0,
) -> Curve:
    """Derive ``max(0, (W - excess_work - unfinished_work) / a)``.

    Required on EVERY backlogged interval covered by this service curve:

    * ``W`` bounds effective work actually delivered by the allocated workers,
      not nominal capacity that scheduling or blocking can make unavailable.
    * For the useful quantity Q completed in that interval, work attributable
      to those outputs PLUS unsuccessful, discarded, and duplicate work is
      at most ``a * Q + excess_work``.
    * Work delivered but still in progress at the interval's end is at most
      ``unfinished_work`` across all active lanes.

    Thus W <= a*Q+b+M, giving the returned quantity service. The aggregate
    cost relation permits individual slow jobs to be offset by fast ones;
    it does not multiply a per-job worst case by an invocation count. A
    relation known only from the initial epoch gives only a prefix bound,
    not this interval-service guarantee. Unbounded failure/retry work or
    unbounded packet sizes cannot be omitted from b or M.
    """
    _nondecreasing(work_service, "work service")
    if work_service.value(0) != 0:
        raise QuantityError("work service must start at zero")
    rate = _rational(work_per_quantity)
    burst = _rational(excess_work)
    unfinished = _rational(unfinished_work)
    if rate <= 0:
        raise QuantityError("work_per_quantity must be positive")
    if burst < 0 or unfinished < 0:
        raise QuantityError("excess_work and unfinished_work must be nonnegative")
    return work_service.sub(Curve.constant(burst + unfinished)).scale(1 / rate).maximum(
        Curve.constant(0),
    )


def running_maximum(curve: Curve) -> Curve:
    """Return ``sup(0 <= s <= t, curve(s))`` exactly.

    Taking this closure strengthens a cumulative lower bound: cumulative
    progress at t cannot be smaller than already guaranteed progress at s.
    It does not claim that a replenishable inventory is nondecreasing.
    """
    highest = curve.value(0)
    points: list[tuple[Fraction, Fraction]] = [(Fraction(0), highest)]
    for (start, left), (end, right) in zip(curve.points, curve.points[1:]):
        if right > highest:
            if left < highest:
                crossing = start + (highest - left) * (end - start) / (right - left)
                points.append((crossing, highest))
            highest = right
        points.append((end, highest))
    start, value = curve.points[-1]
    if curve.tail_slope > 0 and value < highest:
        points.append((start + (highest - value) / curve.tail_slope, highest))
    return Curve(tuple(points), max(Fraction(0), curve.tail_slope))


def ordered_prefix_lower(completed_lower: Curve, withheld_upper: Curve) -> Curve:
    """Bound usable ordered progress after accounting for completed gaps.

    The supplied upper curve must bound TOTAL quantity already completed
    but not usable in the required contiguous prefix. Merely counting missing
    items or bounding one missing item's size is insufficient: one early gap
    can strand arbitrarily many later completions. Source proof or an explicit
    scheduling/reordering envelope must justify the withheld quantity bound.
    Withheld quantity is a stock, not cumulative traffic: its upper bound may
    decrease when a missing predecessor arrives. No stream matching or
    identity claim is inferred from quantity counts.
    """
    _nondecreasing(completed_lower, "completed lower")
    try:
        nonnegative = withheld_upper.infimum() >= 0
    except CurveError:
        nonnegative = False
    if not nonnegative:
        raise QuantityError("withheld upper must be nonnegative")
    return running_maximum(
        completed_lower.sub(withheld_upper).maximum(Curve.constant(0)),
    )
