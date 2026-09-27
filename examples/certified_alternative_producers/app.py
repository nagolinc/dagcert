from dataclasses import dataclass

from dagcert.runtime import operation


@dataclass(frozen=True)
class Request:
    value: str


@dataclass(frozen=True)
class ReservedRequest:
    value: str


@dataclass(frozen=True)
class BuiltRequest:
    value: str


@operation
def reserve_startup(request: Request) -> ReservedRequest:
    return ReservedRequest(request.value)


@operation
def reserve_submitted(request: Request) -> ReservedRequest:
    return ReservedRequest(request.value)


@operation
def build_request(request: ReservedRequest) -> BuiltRequest:
    return BuiltRequest(request.value)
