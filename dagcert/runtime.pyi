from dataclasses import dataclass
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

class OperationTypeViolation(TypeError): ...

@dataclass(frozen=True, slots=True)
class UnhandledException:
    exception_type: str
    message: str

def operation(function: Callable[P, R]) -> Callable[P, R]: ...
def outcome_type(value: object) -> str: ...
