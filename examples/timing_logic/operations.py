"""An executable release policy, not an observer of a completed benchmark.

The caller supplies an atomic acknowledgement snapshot and its monotonic clock
timestamp. The returned decision is the policy's state transition. Network
delivery, clock integrity and bounded dispatch/application remain explicit
platform obligations in the surrounding model.
"""

from dataclasses import dataclass

from dagcert.runtime import operation


@dataclass(frozen=True)
class ReleaseRequest:
    expected_version: int
    now_ms: int
    a_present: bool
    a_replica: int
    a_version: int
    a_arrived_ms: int
    b_present: bool
    b_replica: int
    b_version: int
    b_arrived_ms: int
    c_present: bool
    c_replica: int
    c_version: int
    c_arrived_ms: int


@dataclass(frozen=True)
class ReleaseDecision:
    released: bool
    release_ms: int


@operation
def decide_release(request: ReleaseRequest) -> ReleaseDecision:
    """Release on two distinct, arrived acknowledgements for this version."""
    valid_a = (
        request.a_present and request.a_replica >= 0
        and request.a_version == request.expected_version
        and 0 <= request.a_arrived_ms <= request.now_ms
    )
    valid_b = (
        request.b_present and request.b_replica >= 0
        and request.b_version == request.expected_version
        and 0 <= request.b_arrived_ms <= request.now_ms
    )
    valid_c = (
        request.c_present and request.c_replica >= 0
        and request.c_version == request.expected_version
        and 0 <= request.c_arrived_ms <= request.now_ms
    )
    if (
        (valid_a and valid_b and request.a_replica != request.b_replica)
        or (valid_a and valid_c and request.a_replica != request.c_replica)
        or (valid_b and valid_c and request.b_replica != request.c_replica)
    ):
        return ReleaseDecision(True, request.now_ms)
    return ReleaseDecision(False, 0)
