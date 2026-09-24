"""Small source-typed operations used by the structured pipeline example."""

from __future__ import annotations

from dataclasses import dataclass

from dagcert.runtime import operation


@dataclass(frozen=True)
class RawJob:
    value: int


@dataclass(frozen=True)
class PreparedJob:
    value: int


@dataclass(frozen=True)
class ValidatedJob:
    value: int


@dataclass(frozen=True)
class ChecksummedJob:
    value: int


@dataclass(frozen=True)
class PublishInput:
    validation: ValidatedJob
    checksum: ChecksummedJob


@dataclass(frozen=True)
class PublishedJob:
    value: int


@operation
def prepare(request: RawJob) -> PreparedJob:
    return PreparedJob(request.value)


@operation
def validate(request: PreparedJob) -> ValidatedJob:
    return ValidatedJob(request.value)


@operation
def checksum(request: PreparedJob) -> ChecksummedJob:
    return ChecksummedJob(request.value + 1)


@operation
def publish(request: PublishInput) -> PublishedJob:
    # The source type is the join: publication cannot be called without both branch results.
    # This toy emits a fixed receipt value so the example stays focused on workflow structure.
    return PublishedJob(1)
