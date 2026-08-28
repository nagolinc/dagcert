"""Runtime boundary for source-typed Dagcert operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ParamSpec, TypeVar


P = ParamSpec("P")
R = TypeVar("R")


class OperationTypeViolation(TypeError):
    """Raised internally when an invocation violates its source annotations."""


@dataclass(frozen=True, slots=True)
class UnhandledException:
    """Legacy v4 evidence sentinel; v5 operations may not declare or budget it."""

    exception_type: str
    message: str


def operation(function: Callable[P, R]) -> Callable[P, R]:
    """Mark a real operation without changing its source-declared callable type.

    New certificates require Nagini to prove that the operation body has no undeclared
    exceptional exit. Expected failures therefore belong in the explicit return union; Dagcert
    no longer hides an unexpected exception by widening every operation to a catch-all outcome.
    """

    return function


def outcome_type(value: object) -> str:
    """Return the source-union spelling used in v4 timing evidence."""
    if isinstance(value, UnhandledException):
        return "dagcert.runtime.UnhandledException"
    return type(value).__qualname__
