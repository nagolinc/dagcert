"""Runtime boundary for source-typed Dagcert operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import fields, is_dataclass
from functools import wraps
from inspect import signature
from types import UnionType
from typing import Annotated, Any, Callable, Literal, ParamSpec, TypeVar, Union, get_args, get_origin, get_type_hints


P = ParamSpec("P")
R = TypeVar("R")


class OperationTypeViolation(TypeError):
    """Raised internally when an invocation violates its source annotations."""


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
            hints = get_type_hints(function, include_extras=True)
            bound = signature(function).bind(*args, **kwargs)
            for name, value in bound.arguments.items():
                annotation = hints.get(name)
                if annotation is None or not _matches_annotation(value, annotation, set()):
                    raise OperationTypeViolation(
                        f"input {name!r} does not match the source annotation"
                    )
            result = function(*args, **kwargs)
            return_annotation = hints.get("return")
            if return_annotation is None or not _matches_annotation(
                result, return_annotation, set(),
            ):
                raise OperationTypeViolation(
                    "returned value does not match the source-declared outcome union"
                )
            return result
        except BaseException as exc:
            return UnhandledException(type(exc).__qualname__, str(exc))

    return guarded


def outcome_type(value: object) -> str:
    """Return the source-union spelling used in v4 timing evidence."""
    if isinstance(value, UnhandledException):
        return "dagcert.runtime.UnhandledException"
    return type(value).__qualname__


def _matches_annotation(value: object, annotation: object, seen: set[tuple[int, str]]) -> bool:
    """Validate the closed runtime values that cross a Dagcert operation boundary."""

    if annotation is Any:
        return False
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in {Union, UnionType}:
        return any(_matches_annotation(value, item, seen) for item in arguments)
    if origin is Annotated:
        return bool(arguments) and _matches_annotation(value, arguments[0], seen)
    if origin is Literal:
        return any(type(value) is type(item) and value == item for item in arguments)
    if annotation is None or annotation is type(None):
        return value is None

    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return all(_matches_annotation(item, arguments[0], seen) for item in value)
        return len(value) == len(arguments) and all(
            _matches_annotation(item, expected, seen)
            for item, expected in zip(value, arguments, strict=True)
        )
    if origin in {list, set, frozenset, Sequence}:
        expected_type = {
            list: list, set: set, frozenset: frozenset, Sequence: Sequence,
        }[origin]
        return isinstance(value, expected_type) and (
            not arguments
            or all(_matches_annotation(item, arguments[0], seen) for item in value)
        )
    if origin in {dict, Mapping}:
        if not isinstance(value, Mapping):
            return False
        if len(arguments) != 2:
            return not arguments
        return all(
            _matches_annotation(key, arguments[0], seen)
            and _matches_annotation(item, arguments[1], seen)
            for key, item in value.items()
        )
    if origin is type:
        if not isinstance(value, type) or not arguments:
            return isinstance(value, type)
        try:
            return issubclass(value, arguments[0])
        except TypeError:
            return False
    if origin is not None:
        try:
            if not isinstance(value, origin):
                return False
        except TypeError:
            return False
        return not arguments

    if annotation in {bool, int, float, complex, str, bytes}:
        return type(value) is annotation
    if not isinstance(annotation, type) or not isinstance(value, annotation):
        return False
    if not is_dataclass(value):
        return True

    marker = (id(value), f"{annotation.__module__}.{annotation.__qualname__}")
    if marker in seen:
        return True
    seen.add(marker)
    try:
        field_hints = get_type_hints(annotation, include_extras=True)
    except BaseException:
        return False
    return all(
        field.name in field_hints
        and _matches_annotation(getattr(value, field.name), field_hints[field.name], seen)
        for field in fields(value)
    )
