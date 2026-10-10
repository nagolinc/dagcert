"""Typed units of work; scheduling and arrival envelopes live in the contract."""

from dataclasses import dataclass

from dagcert.runtime import operation


@dataclass(frozen=True)
class WorkRequest:
    sequence: int


@dataclass(frozen=True)
class ProducedItem:
    sequence: int


@dataclass(frozen=True)
class ConsumptionReceipt:
    sequence: int


@operation
def produce_first(request: WorkRequest) -> ProducedItem:
    return ProducedItem(request.sequence)


@operation
def produce_second(request: WorkRequest) -> ProducedItem:
    return ProducedItem(request.sequence)


@operation
def consume(request: WorkRequest) -> ConsumptionReceipt:
    return ConsumptionReceipt(request.sequence)
