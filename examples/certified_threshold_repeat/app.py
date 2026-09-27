from dataclasses import dataclass
from typing import Union

from dagcert.runtime import operation


@dataclass(frozen=True)
class PreparationRequest:
    value: int


@dataclass(frozen=True)
class PreparedItem:
    value: int


@dataclass(frozen=True)
class PreparationRejected:
    reason: str


@operation
def prepare(request: PreparationRequest) -> Union[PreparedItem, PreparationRejected]:
    if request.value >= 0:
        return PreparedItem(request.value)
    return PreparationRejected("negative value")
