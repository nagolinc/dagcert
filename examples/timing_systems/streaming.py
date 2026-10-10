"""Small variable-quantity producer and bounded-buffer refill policy.

The example produces segment descriptors, not real video. Platform rendering
cost and scheduler restart time remain visible engineering envelopes.
"""

from dataclasses import dataclass
from typing import Union

from dagcert.runtime import operation


@dataclass(frozen=True)
class SegmentRequest:
    sequence: int
    duration_ms: int
    maximum_ms: int
    provider_succeeded: bool


@dataclass(frozen=True)
class SegmentProduced:
    sequence: int
    duration_ms: int


@dataclass(frozen=True)
class SegmentFailed:
    sequence: int


@operation
def produce_segment(request: SegmentRequest) -> Union[SegmentProduced, SegmentFailed]:
    if (
        request.sequence < 0 or request.duration_ms <= 0
        or request.duration_ms > request.maximum_ms or not request.provider_succeeded
    ):
        return SegmentFailed(request.sequence)
    return SegmentProduced(request.sequence, request.duration_ms)


@dataclass(frozen=True)
class RefillRequest:
    reserve_ms: int
    capacity_ms: int
    low_water_ms: int
    maximum_piece_ms: int


@dataclass(frozen=True)
class RefillDecision:
    reserve_ms: int
    capacity_ms: int
    refill: bool


@operation
def decide_refill(request: RefillRequest) -> RefillDecision:
    valid = (
        request.reserve_ms >= 0 and request.reserve_ms <= request.capacity_ms
        and request.low_water_ms > 0 and request.maximum_piece_ms > 0
        and request.low_water_ms + request.maximum_piece_ms <= request.capacity_ms
    )
    return RefillDecision(
        request.reserve_ms, request.capacity_ms,
        valid and request.reserve_ms < request.low_water_ms,
    )


@dataclass(frozen=True)
class ConsumptionRequest:
    duration_ms: int
    reserve_ms: int
    capacity_ms: int


@dataclass(frozen=True)
class Consumed:
    duration_ms: int
    remaining_ms: int
    capacity_ms: int


@dataclass(frozen=True)
class BufferEmpty:
    remaining_ms: int
    capacity_ms: int


@operation
def consume(request: ConsumptionRequest) -> Union[Consumed, BufferEmpty]:
    if request.duration_ms <= 0 or request.reserve_ms < request.duration_ms:
        return BufferEmpty(request.reserve_ms, request.capacity_ms)
    return Consumed(request.duration_ms, request.reserve_ms - request.duration_ms, request.capacity_ms)
