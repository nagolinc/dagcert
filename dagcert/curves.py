"""Exact continuous piecewise-affine curves for real-time calculus.

Curves have finitely many breakpoints and an affine final ray on nonnegative
time. Arithmetic uses rational numbers throughout. Min-plus operations find
all candidate segments and their intersections; they never sample a time grid.
The class deliberately permits negative values and slopes, since subtracting
production and consumption envelopes gives inventory bounds of that form.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Iterable, TypeAlias


Scalar: TypeAlias = int | float | str | Fraction


class CurveError(ValueError):
    """A curve is malformed or the requested finite result does not exist."""


def _rational(value: Scalar) -> Fraction:
    if isinstance(value, bool):
        raise CurveError("curve numbers must not be booleans")
    try:
        return value if isinstance(value, Fraction) else Fraction(str(value))
    except (ValueError, ZeroDivisionError, TypeError, OverflowError) as error:
        raise CurveError(f"curve number must be finite and rational: {value!r}") from error


@dataclass(frozen=True, slots=True)
class _Segment:
    start: Fraction
    end: Fraction | None
    slope: Fraction
    intercept: Fraction

    def contains(self, time: Fraction) -> bool:
        return self.start <= time and (self.end is None or time <= self.end)

    def value(self, time: Fraction) -> Fraction:
        return self.slope * time + self.intercept


@dataclass(frozen=True, slots=True)
class Curve:
    """A continuous curve, with ``points[0].time == 0`` and an affine tail."""

    points: tuple[tuple[Fraction, Fraction], ...]
    tail_slope: Fraction = Fraction(0)

    def __post_init__(self) -> None:
        points = tuple((_rational(time), _rational(value)) for time, value in self.points)
        tail_slope = _rational(self.tail_slope)
        if not points or points[0][0] != 0:
            raise CurveError("curve points must start at time zero")
        if any(left[0] >= right[0] for left, right in zip(points, points[1:])):
            raise CurveError("curve point times must be strictly increasing")
        # Canonicalize redundant collinear points without changing the function.
        reduced: list[tuple[Fraction, Fraction]] = []
        for point in points:
            while len(reduced) >= 2:
                left, middle = reduced[-2:]
                if (
                    (middle[1] - left[1]) * (point[0] - middle[0])
                    != (point[1] - middle[1]) * (middle[0] - left[0])
                ):
                    break
                reduced.pop()
            reduced.append(point)
        while len(reduced) > 1:
            left, right = reduced[-2:]
            if right[1] - left[1] != tail_slope * (right[0] - left[0]):
                break
            reduced.pop()
        object.__setattr__(self, "points", tuple(reduced))
        object.__setattr__(self, "tail_slope", tail_slope)

    @classmethod
    def from_points(
        cls, points: Iterable[tuple[Scalar, Scalar]], tail_slope: Scalar = 0,
    ) -> Curve:
        """Parse decimal inputs exactly, including JSON decimal numbers."""
        return cls(
            tuple((_rational(time), _rational(value)) for time, value in points),
            _rational(tail_slope),
        )

    @classmethod
    def constant(cls, value: Scalar) -> Curve:
        return cls(((Fraction(0), _rational(value)),))

    def value(self, time: Scalar) -> Fraction:
        position = _rational(time)
        if position < 0:
            raise CurveError("curve time must be nonnegative")
        index = bisect_right(self.points, position, key=lambda point: point[0]) - 1
        start, value = self.points[index]
        if index == len(self.points) - 1:
            slope = self.tail_slope
        else:
            end, next_value = self.points[index + 1]
            slope = (next_value - value) / (end - start)
        return value + slope * (position - start)

    def add(self, other: Curve) -> Curve:
        times = sorted({time for time, _ in self.points + other.points})
        return Curve(
            tuple((time, self.value(time) + other.value(time)) for time in times),
            self.tail_slope + other.tail_slope,
        )

    def sub(self, other: Curve) -> Curve:
        return self.add(other.scale(-1))

    def scale(self, factor: Scalar) -> Curve:
        multiplier = _rational(factor)
        return Curve(
            tuple((time, value * multiplier) for time, value in self.points),
            self.tail_slope * multiplier,
        )

    def minimum(self, other: Curve) -> Curve:
        return _envelope(self._segments() + other._segments(), lower=True)

    def maximum(self, other: Curve) -> Curve:
        return _envelope(self._segments() + other._segments(), lower=False)

    def shift(self, delay: Scalar) -> Curve:
        """Return ``self(max(0, t - delay))``; hold the initial value before delay."""
        offset = _rational(delay)
        if offset < 0:
            raise CurveError("curve shift delay must be nonnegative")
        if offset == 0:
            return self
        return Curve(
            ((Fraction(0), self.points[0][1]),)
            + tuple((time + offset, value) for time, value in self.points),
            self.tail_slope,
        )

    def infimum(self, start: Scalar = 0, end: Scalar | None = None) -> Fraction:
        return self._extremum(start, end, lower=True)

    def supremum(self, start: Scalar = 0, end: Scalar | None = None) -> Fraction:
        return self._extremum(start, end, lower=False)

    def convolution(self, other: Curve) -> Curve:
        """Return the min-plus convolution ``inf(self(s) + other(t-s))``.

        For fixed t, the minimum of the piecewise-affine function of s on
        [0, t] occurs at an endpoint or a knot of either summand. Fixing each
        such knot generates all affine candidates on the appropriate domains.
        """
        candidates: list[_Segment] = []
        for left, right in ((self, other), (other, self)):
            right_segments = right._segments()
            for time, value in left.points:
                for segment in right_segments:
                    candidates.append(_Segment(
                        time + segment.start,
                        None if segment.end is None else time + segment.end,
                        segment.slope,
                        value + segment.intercept - segment.slope * time,
                    ))
        return _envelope(tuple(candidates), lower=True)

    def deconvolution(self, other: Curve) -> Curve:
        """Return ``sup_u>=0(self(t+u) - other(u))`` or reject an infinite result.

        The maximum occurs at u=0 or a knot of either summand, unless the final
        affine ray grows without bound. Equal tail slopes also contribute the
        tail value, which is attained for sufficiently large u at every t.
        """
        if self.tail_slope > other.tail_slope:
            raise CurveError("min-plus deconvolution is unbounded above")
        candidates: list[_Segment] = []
        left_segments, right_segments = self._segments(), other._segments()
        # A knot of other fixes u; move every segment of self to the left by u.
        for time, value in other.points:
            for segment in left_segments:
                end = None if segment.end is None else segment.end - time
                if end is not None and end < 0:
                    continue
                candidates.append(_Segment(
                    max(Fraction(0), segment.start - time),
                    end,
                    segment.slope,
                    segment.intercept + segment.slope * time - value,
                ))
        # A knot a of self fixes t+u=a, so u=a-t and 0 <= t <= a.
        for time, value in self.points:
            for segment in right_segments:
                end = time - segment.start
                if end < 0:
                    continue
                start = Fraction(0) if segment.end is None else max(
                    Fraction(0), time - segment.end,
                )
                candidates.append(_Segment(
                    start, end, segment.slope,
                    value - segment.intercept - segment.slope * time,
                ))
        if self.tail_slope == other.tail_slope:
            candidates.append(_Segment(
                Fraction(0), None, self.tail_slope,
                left_segments[-1].intercept - right_segments[-1].intercept,
            ))
        return _envelope(tuple(candidates), lower=False)

    def _segments(self) -> tuple[_Segment, ...]:
        segments: list[_Segment] = []
        for (start, value), (end, next_value) in zip(self.points, self.points[1:]):
            slope = (next_value - value) / (end - start)
            segments.append(_Segment(start, end, slope, value - slope * start))
        start, value = self.points[-1]
        segments.append(_Segment(start, None, self.tail_slope, value - self.tail_slope * start))
        return tuple(segments)

    def _extremum(self, start: Scalar, end: Scalar | None, *, lower: bool) -> Fraction:
        first = _rational(start)
        last = None if end is None else _rational(end)
        if first < 0 or (last is not None and last < first):
            raise CurveError("curve extremum requires 0 <= start <= end")
        if last is None:
            if lower and self.tail_slope < 0:
                raise CurveError("curve infimum is unbounded below")
            if not lower and self.tail_slope > 0:
                raise CurveError("curve supremum is unbounded above")
        values = [self.value(first)]
        values.extend(
            value for time, value in self.points
            if time >= first and (last is None or time <= last)
        )
        if last is not None:
            values.append(self.value(last))
        return min(values) if lower else max(values)


def _envelope(segments: tuple[_Segment, ...], *, lower: bool) -> Curve:
    """Compute an exact lower/upper envelope of domain-restricted affine pieces."""
    segments = tuple(dict.fromkeys(segments))
    times = {Fraction(0)}
    for segment in segments:
        times.add(segment.start)
        if segment.end is not None:
            times.add(segment.end)
    for left, right in combinations(segments, 2):
        if left.slope == right.slope:
            continue
        crossing = (right.intercept - left.intercept) / (left.slope - right.slope)
        if left.contains(crossing) and right.contains(crossing):
            times.add(crossing)
    points: list[tuple[Fraction, Fraction]] = []
    for time in sorted(times):
        values = [segment.value(time) for segment in segments if segment.contains(time)]
        if not values:
            raise CurveError("curve operation produced an uncovered time interval")
        points.append((time, min(values) if lower else max(values)))
    # Every crossing and finite endpoint is behind this probe. The extremal
    # affine piece therefore remains extremal for the entire final ray.
    probe = points[-1][0] + 1
    rays = [segment for segment in segments if segment.end is None]
    if not rays:
        raise CurveError("curve operation has no final affine ray")
    selected = min(rays, key=lambda segment: segment.value(probe)) if lower else max(
        rays, key=lambda segment: segment.value(probe),
    )
    return Curve(tuple(points), selected.slope)
