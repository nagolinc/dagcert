"""Durable runtime violations. Persistence and the error log are always enabled."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from time import time
from typing import Any, Mapping
from uuid import uuid4

_lock = RLock()
_events: list[dict[str, Any]] = []


def record_violation(
    promise_id: str, *, expected: object, observed: object,
    context: Mapping[str, object] | None = None, message: str = "",
    directory: str | Path | None = None, remember: bool = True,
) -> dict[str, Any]:
    """Publish one failure without requiring a logger, observer, or environment flag.

    Storage errors propagate: a caller must never believe an unrecorded violation
    was retained. Applications may select their data directory at construction;
    otherwise the conventional .dagcert directory in the working directory is used.
    """
    row = dict(context or {})
    row.update(id=uuid4().hex, promise_id=promise_id, expected=expected,
               observed=observed, message=message or f"Promise {promise_id} was violated",
               recorded_at=time(), violation=True, passed=False, active=True)
    line = json.dumps(row, allow_nan=False, ensure_ascii=False) + "\n"
    path = Path(directory) if directory is not None else Path.cwd() / ".dagcert"
    with _lock:
        path.mkdir(parents=True, exist_ok=True)
        with (path / "violations.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
        if remember:
            _events.append(row)
    logging.getLogger("dagcert.runtime").error("DAGCERT VIOLATION %s", line.rstrip())
    return row


def promise_violations() -> tuple[dict[str, Any], ...]:
    with _lock:
        return tuple(dict(row) for row in _events)


def clear_promise_violations() -> None:
    """Clear process memory between isolated tests; never delete the durable log."""
    with _lock:
        _events.clear()
