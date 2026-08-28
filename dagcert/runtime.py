"""Runtime boundaries for proved operations and explicitly assumed external calls."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import logging
from inspect import signature
from threading import RLock
from time import perf_counter, time
from typing import Callable, Generic, Iterator, ParamSpec, TypeVar, get_type_hints

from typeguard import TypeCheckError, check_type


P = ParamSpec("P")
R = TypeVar("R")


_LOG = logging.getLogger("dagcert.runtime")
_EXTERNAL_RAISED = "dagcert.runtime.ExternalRaised"
_EXTERNAL_TYPE_VIOLATION = "dagcert.runtime.ExternalTypeViolation"


class OperationTypeViolation(TypeError):
    """Raised internally when an invocation violates its source annotations."""


@dataclass(frozen=True, slots=True)
class UnhandledException:
    """Legacy v4 evidence sentinel; v5 operations may not declare or budget it."""

    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ExternalSuccess(Generic[R]):
    """A runtime-validated value returned by a declared external boundary."""

    value: R


@dataclass(frozen=True, slots=True)
class ExternalRaised:
    """A declared external call raised instead of returning its assumed success type."""

    boundary_id: str
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ExternalTypeViolation:
    """A declared external call returned a value outside its source return annotation."""

    boundary_id: str
    expected_type: str
    observed_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ExternalBoundaryEvent:
    """One production external-boundary observation published to Dagcert monitors."""

    boundary_id: str
    elapsed_ms: float
    outcome_type: str
    succeeded: bool
    recorded_at: float
    expected_type: str
    observed_type: str | None = None
    exception_type: str | None = None
    message: str | None = None


class ExternalMonitorError(RuntimeError):
    """Dagcert could not publish a boundary event to an installed monitor."""


ExternalResult = ExternalSuccess[R] | ExternalRaised | ExternalTypeViolation
ExternalObserver = Callable[[ExternalBoundaryEvent], None]


_observer_lock = RLock()
_external_observers: list[ExternalObserver] = []
_runtime_violations: list[ExternalBoundaryEvent] = []


def operation(function: Callable[P, R]) -> Callable[P, R]:
    """Mark a real operation without changing its source-declared callable type.

    New certificates require Nagini to prove that the operation body has no undeclared
    exceptional exit. Expected failures therefore belong in the explicit return union; Dagcert
    no longer hides an unexpected exception by widening every operation to a catch-all outcome.
    """

    return function


def external_boundary(
    boundary_id: str,
) -> Callable[[Callable[P, R]], Callable[P, ExternalResult[R]]]:
    """Wrap one external-library adapter in a typed, monitored outcome boundary."""

    if not isinstance(boundary_id, str) or not boundary_id.strip():
        raise ValueError("external boundary ID must be a nonempty string")
    identifier = boundary_id.strip()

    def decorate(function: Callable[P, R]) -> Callable[P, ExternalResult[R]]:
        hints = get_type_hints(function)
        if "return" not in hints:
            raise TypeError(
                f"external boundary {identifier} implementation lacks a return annotation"
            )
        expected_type = hints["return"]
        expected_label = _type_name(expected_type)
        function_signature = signature(function)

        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> ExternalResult[R]:
            started = perf_counter()
            try:
                bound = function_signature.bind(*args, **kwargs)
                for parameter, value in bound.arguments.items():
                    parameter_type = hints.get(parameter)
                    if parameter_type is not None:
                        check_type(value, parameter_type)
            except (TypeCheckError, TypeError) as exc:
                observed = _type_name(type(args[0])) if args else "invalid-call-shape"
                event = ExternalBoundaryEvent(
                    identifier,
                    (perf_counter() - started) * 1000,
                    _EXTERNAL_TYPE_VIOLATION,
                    False,
                    time(),
                    "source-declared external input",
                    observed_type=observed,
                    exception_type=_type_name(type(exc)),
                    message=str(exc),
                )
                _publish_external_event(event)
                return ExternalTypeViolation(
                    identifier, event.expected_type, observed, str(exc),
                )
            try:
                value = function(*args, **kwargs)
            except Exception as exc:
                event = ExternalBoundaryEvent(
                    identifier,
                    (perf_counter() - started) * 1000,
                    _EXTERNAL_RAISED,
                    False,
                    time(),
                    expected_label,
                    exception_type=_type_name(type(exc)),
                    message=str(exc),
                )
                _publish_external_event(event)
                return ExternalRaised(
                    identifier, str(event.exception_type), str(event.message or ""),
                )
            except BaseException as exc:
                event = ExternalBoundaryEvent(
                    identifier,
                    (perf_counter() - started) * 1000,
                    _EXTERNAL_RAISED,
                    False,
                    time(),
                    expected_label,
                    exception_type=_type_name(type(exc)),
                    message=str(exc),
                )
                _publish_external_event(event)
                raise

            try:
                check_type(value, expected_type)
            except (TypeCheckError, TypeError) as exc:
                observed = _type_name(type(value))
                event = ExternalBoundaryEvent(
                    identifier,
                    (perf_counter() - started) * 1000,
                    _EXTERNAL_TYPE_VIOLATION,
                    False,
                    time(),
                    expected_label,
                    observed_type=observed,
                    exception_type=_type_name(type(exc)),
                    message=str(exc),
                )
                _publish_external_event(event)
                return ExternalTypeViolation(
                    identifier, expected_label, observed, str(exc),
                )

            _publish_external_event(ExternalBoundaryEvent(
                identifier,
                (perf_counter() - started) * 1000,
                type(value).__qualname__,
                True,
                time(),
                expected_label,
                observed_type=_type_name(type(value)),
            ))
            return ExternalSuccess(value)

        return wrapped

    return decorate


@contextmanager
def monitor_external_boundaries(observer: ExternalObserver) -> Iterator[None]:
    """Install a process-wide observer, including calls made by worker threads."""

    if not callable(observer):
        raise TypeError("external boundary observer must be callable")
    with _observer_lock:
        _external_observers.append(observer)
    try:
        yield
    finally:
        with _observer_lock:
            _external_observers.remove(observer)


def runtime_violations() -> tuple[ExternalBoundaryEvent, ...]:
    """Return every external failure observed by this process."""

    with _observer_lock:
        return tuple(_runtime_violations)


def clear_runtime_violations() -> None:
    """Clear process-local violations between isolated test/application runs."""

    with _observer_lock:
        _runtime_violations.clear()


def _publish_external_event(event: ExternalBoundaryEvent) -> None:
    with _observer_lock:
        if not event.succeeded:
            _runtime_violations.append(event)
            _LOG.error(
                "DAGCERT VIOLATION external boundary %s produced %s: %s",
                event.boundary_id,
                event.outcome_type,
                event.message or "external contract failed",
            )
        observers = tuple(_external_observers)
    for observer in observers:
        try:
            observer(event)
        except Exception as exc:
            raise ExternalMonitorError(
                f"external boundary monitor failed for {event.boundary_id}: {exc}"
            ) from exc


def _type_name(value: object) -> str:
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return qualname if module == "builtins" else f"{module}.{qualname}"
    return str(value)


def outcome_type(value: object) -> str:
    """Return the source-union spelling used in v4 timing evidence."""
    if isinstance(value, UnhandledException):
        return "dagcert.runtime.UnhandledException"
    if isinstance(value, ExternalSuccess):
        return type(value.value).__qualname__
    if isinstance(value, ExternalRaised):
        return _EXTERNAL_RAISED
    if isinstance(value, ExternalTypeViolation):
        return _EXTERNAL_TYPE_VIOLATION
    return type(value).__qualname__
