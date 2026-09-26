"""Source-owned total operations on both sides of one asynchronous queue."""

from dataclasses import dataclass
from typing import Union

from dagcert.runtime import operation


@dataclass(frozen=True)
class NewJob:
    value: str


@dataclass(frozen=True)
class PreparedJob:
    value: str


@dataclass(frozen=True)
class QueuePutRequest:
    job: PreparedJob


@dataclass(frozen=True)
class QueuePutResponse:
    status: str
    job: PreparedJob
    message: str


@dataclass(frozen=True)
class QueuePutFailed:
    message: str


@dataclass(frozen=True)
class QueueTakePolicy:
    blocking: bool


@dataclass(frozen=True)
class QueueTakeRequest:
    blocking: bool


@dataclass(frozen=True)
class QueueTakeResponse:
    status: str
    job: PreparedJob
    message: str


@dataclass(frozen=True)
class JobTaken:
    value: str


@dataclass(frozen=True)
class QueueTakeFailed:
    message: str


@dataclass(frozen=True)
class Delivered:
    value: str


@operation
def prepare_job(request: NewJob) -> PreparedJob:
    return PreparedJob(request.value)


@operation
def build_put_request(request: PreparedJob) -> QueuePutRequest:
    return QueuePutRequest(request)


@operation
def classify_put(
    response: QueuePutResponse,
) -> Union[PreparedJob, QueuePutFailed]:
    if response.status == "queued":
        return response.job
    return QueuePutFailed(response.message)


@operation
def build_take_request(request: QueueTakePolicy) -> QueueTakeRequest:
    return QueueTakeRequest(request.blocking)


@operation
def classify_take(
    response: QueueTakeResponse,
) -> Union[JobTaken, QueueTakeFailed]:
    if response.status == "taken":
        return JobTaken(response.job.value)
    return QueueTakeFailed(response.message)


@operation
def deliver(request: JobTaken) -> Delivered:
    return Delivered(request.value)
