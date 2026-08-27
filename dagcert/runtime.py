"""Runtime boundary for source-typed Dagcert operations."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Callable, ParamSpec, TypeVar


P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class UnhandledException:
    """The mandatory outcome for an exception escaping an operation body."""

    exception_type: str
    message: str


def operation(function: Callable[P, R]) -> Callable[P, R | UnhandledException]:
    """Turn every escaped Python exception into a real, typed task outcome.

    Expected operational failures should be caught in the function and returned as one of its
    explicit source-declared variants.  This guard prevents an exception from silently becoming
    a missing queue item outside the task's formal outcome union.
    """

    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> R | UnhandledException:
        try:
            return function(*args, **kwargs)
        except BaseException as exc:
            return UnhandledException(type(exc).__qualname__, str(exc))

    return guarded


def outcome_type(value: object) -> str:
    """Return the source-union spelling used in v4 timing evidence."""
    if isinstance(value, UnhandledException):
        return "dagcert.runtime.UnhandledException"
    return type(value).__qualname__
