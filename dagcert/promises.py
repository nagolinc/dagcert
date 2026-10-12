"""Executable numeric promises, including rolling windows and live deadlines.

The declaration supplies the bound; normal observations supply facts. Dagcert
performs the comparison and retains failures automatically, including missing or
non-finite observations. English assumptions alone are not runtime monitors.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from threading import RLock, Timer
from time import perf_counter
from typing import Mapping, cast

from .promise_events import record_violation


@dataclass(frozen=True)
class Promise:
    id: str
    event: str
    field: str
    operator: str
    bound: float
    window: int = 1
    group_by: str = "story_id"
    rolling: bool = True

    def __post_init__(self) -> None:
        if not all(isinstance(v, str) and v for v in (self.id, self.event, self.field, self.group_by)):
            raise ValueError("Promise identities and field names must be nonempty strings")
        if self.operator not in {">=", "<=", "=="}:
            raise ValueError("Promise operator must be >=, <=, or ==")
        if type(self.bound) not in (int, float) or not isfinite(self.bound):
            raise ValueError("Promise bound must be finite")
        if type(self.window) is not int or self.window < 1:
            raise ValueError("Promise window must be a positive integer")
        if type(self.rolling) is not bool:
            raise ValueError("Promise rolling must be boolean")

    def accepts(self, value: object) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
            return False
        return {">=": value >= self.bound, "<=": value <= self.bound,
                "==": value == self.bound}[self.operator]


class PromiseMonitor:
    def __init__(self, promises: list[Promise], *, directory: str | Path | None = None,
                 identity: Mapping[str, object] | None = None) -> None:
        if len({p.id for p in promises}) != len(promises):
            raise ValueError("Duplicate runtime promise ID")
        self.promises = tuple(promises)
        self.directory = directory
        self.identity = dict(identity or {})
        self._lock = RLock()
        self._windows: dict[tuple[str, str], deque[float]] = {}
        self._reported: set[tuple[str, str]] = set()

    @classmethod
    def from_file(cls, path: str | Path, *, directory: str | Path | None = None) -> PromiseMonitor:
        content = Path(path).read_bytes()
        raw = json.loads(content)
        if raw.get("schema") != "dagcert-runtime-promises/v1":
            raise ValueError("Unsupported runtime promise schema")
        return cls([Promise(**row) for row in raw["promises"]], directory=directory,
                   identity={"promise_manifest_sha256": sha256(content).hexdigest()})

    def observe(self, event: str, values: Mapping[str, object], *,
                context: Mapping[str, object] | None = None,
                invocation_id: str | None = None) -> bool:
        context = {**self.identity, **dict(context or {})}
        passed = True
        with self._lock:
            for promise in self.promises:
                if promise.event != event:
                    continue
                value = values.get(promise.field)
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                if promise.window > 1 and valid:
                    if promise.group_by not in context:
                        value = None
                    else:
                        group = (promise.id, str(context[promise.group_by]))
                        window = self._windows.setdefault(group, deque(maxlen=promise.window))
                        window.append(float(cast(float, value)))
                        if len(window) < promise.window:
                            continue
                        value = sum(window)
                        if not promise.rolling:
                            window.clear()
                if promise.accepts(value):
                    continue
                passed = False
                key = (promise.id, invocation_id) if invocation_id is not None else None
                if key is not None and key in self._reported:
                    continue
                observed: object = value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else repr(value)
                record_violation(promise.id,
                    expected={"field": promise.field, "operator": promise.operator,
                              "bound": promise.bound, "window": promise.window},
                    observed=observed, context={**context, "event": event,
                                               "invocation_id": invocation_id},
                    directory=self.directory)
                if key is not None:
                    self._reported.add(key)
        return passed

    def start(self, event: str, *, context: Mapping[str, object], invocation_id: str) -> Deadline:
        return Deadline(self, event, context, invocation_id)


class Deadline:
    """Report an elapsed-time breach while work is still running, then cancel safely."""
    def __init__(self, monitor: PromiseMonitor, event: str,
                 context: Mapping[str, object], invocation_id: str) -> None:
        self.monitor, self.event, self.context = monitor, event, dict(context)
        self.invocation_id, self.started = invocation_id, perf_counter()
        self.lock = RLock()
        self.finished = False
        self.timers: list[Timer] = []
        for promise in monitor.promises:
            if promise.event == event and promise.field == "elapsed_ms" and promise.operator == "<=" and promise.window == 1:
                if promise.bound < 0:
                    raise ValueError("Deadline bound cannot be negative")
                timer = Timer(promise.bound / 1000, self._expired, (promise,))
                timer.daemon = True
                self.timers.append(timer)
                timer.start()

    def _expired(self, promise: Promise) -> None:
        with self.lock:
            if not self.finished:
                # Only this deadline is evaluated. Rolling windows count completed
                # invocations once, never timer callbacks plus completion twice.
                elapsed = (perf_counter()-self.started)*1000
                key = (promise.id, self.invocation_id)
                with self.monitor._lock:
                    if elapsed > promise.bound and key not in self.monitor._reported:
                        record_violation(promise.id,
                            expected={"field": "elapsed_ms", "operator": "<=", "bound": promise.bound, "window": 1},
                            observed=elapsed,
                            context={**self.monitor.identity, **self.context, "event": self.event,
                                     "in_progress": True, "invocation_id": self.invocation_id},
                            directory=self.monitor.directory)
                        self.monitor._reported.add(key)

    def finish(self) -> float:
        with self.lock:
            if self.finished:
                raise RuntimeError("Deadline was already finished")
            self.finished = True
            for timer in self.timers:
                timer.cancel()
            elapsed = (perf_counter()-self.started)*1000
            self.monitor.observe(self.event, {"elapsed_ms": elapsed}, context=self.context,
                                 invocation_id=self.invocation_id)
            return elapsed
