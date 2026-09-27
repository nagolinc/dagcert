from dataclasses import dataclass
from typing import Union

from dagcert.runtime import operation


@dataclass(frozen=True)
class PreparationRequest:
    value: int


@dataclass(frozen=True)
class SampledItem:
    value: int


@dataclass(frozen=True)
class SamplingRejected:
    reason: str


@dataclass(frozen=True)
class PreparedItem:
    value: int


@dataclass(frozen=True)
class PreparationRejected:
    reason: str


@operation
def sample(request: PreparationRequest) -> Union[SampledItem, SamplingRejected]:
    if request.value >= 0:
        return SampledItem(request.value)
    return SamplingRejected("negative value")


@operation
def prepare(request: SampledItem) -> Union[PreparedItem, PreparationRejected]:
    if request.value >= 0:
        return PreparedItem(request.value)
    return PreparationRejected("negative value")
