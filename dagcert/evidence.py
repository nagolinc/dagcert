"""Source-bound timing observations for tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, Mapping
import json
from math import isfinite


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TimingSample:
    task_id: str
    case: str
    value_ms: float
    worker_id: str
    source_fingerprint: str
    succeeded: bool = True
    recorded_at: float = field(default_factory=time)
    observed_worker_concurrency: int | None = None
    observed_input_type: str | None = None
    observed_output_type: str | None = None
    outcome_type: str | None = None
    resource_acquired: Mapping[str, float] = field(default_factory=dict)
    resource_consumed: Mapping[str, float] = field(default_factory=dict)
    resource_produced: Mapping[str, float] = field(default_factory=dict)
    resource_levels: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("task_id", "case", "worker_id", "source_fingerprint"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise EvidenceError(f"{field_name} must be a nonempty string")
        if (
            isinstance(self.value_ms, bool)
            or not isinstance(self.value_ms, (int, float))
            or not isfinite(float(self.value_ms))
            or self.value_ms < 0
        ):
            raise EvidenceError("value_ms must be finite and nonnegative")
        if (
            isinstance(self.recorded_at, bool)
            or not isinstance(self.recorded_at, (int, float))
            or not isfinite(float(self.recorded_at))
        ):
            raise EvidenceError("recorded_at must be finite")
        if not isinstance(self.succeeded, bool):
            raise EvidenceError("succeeded must be boolean")
        if self.observed_worker_concurrency is not None and (
            isinstance(self.observed_worker_concurrency, bool)
            or not isinstance(self.observed_worker_concurrency, int)
            or self.observed_worker_concurrency < 1
        ):
            raise EvidenceError("observed_worker_concurrency must be a positive integer")
        for field_name in ("observed_input_type", "observed_output_type", "outcome_type"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise EvidenceError(f"{field_name} must be a nonempty string or null")
        for field_name in (
            "resource_acquired", "resource_consumed", "resource_produced", "resource_levels",
        ):
            _validate_number_mapping(getattr(self, field_name), field_name)
        if not isinstance(self.metadata, Mapping):
            raise EvidenceError("metadata must be an object")

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceRecorder:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, sample: TimingSample) -> None:
        encoded = json.dumps(sample.to_mapping(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)


def load_evidence(path: str | Path) -> tuple[TimingSample, ...]:
    result: list[TimingSample] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            sample = TimingSample(
                task_id=row["task_id"], case=row["case"], value_ms=row["value_ms"],
                worker_id=row["worker_id"], source_fingerprint=row["source_fingerprint"],
                succeeded=row["succeeded"], recorded_at=row["recorded_at"],
                observed_worker_concurrency=row.get("observed_worker_concurrency"),
                observed_input_type=row.get("observed_input_type"),
                observed_output_type=row.get("observed_output_type"),
                outcome_type=row.get("outcome_type"),
                resource_acquired=_number_mapping(row.get("resource_acquired", {})),
                resource_consumed=_number_mapping(row.get("resource_consumed", {})),
                resource_produced=_number_mapping(row.get("resource_produced", {})),
                resource_levels=_number_mapping(row.get("resource_levels", {})),
                metadata=dict(row.get("metadata", {})),
            )
        except (EvidenceError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceError(f"invalid timing evidence line {line_number}: {exc}") from exc
        result.append(sample)
    return tuple(result)


def _number_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise EvidenceError("resource observations must be objects")
    result: dict[str, float] = {}
    for key, amount in value.items():
        if not isinstance(key, str) or not key.strip():
            raise EvidenceError("resource observation IDs must be nonempty strings")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise EvidenceError("resource observation amounts must be numbers")
        result[key] = float(amount)
    return result


def _validate_number_mapping(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{label} must be an object")
    for key, amount in value.items():
        if not isinstance(key, str) or not key.strip():
            raise EvidenceError(f"{label} IDs must be nonempty strings")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not isfinite(float(amount))
            or amount < 0
        ):
            raise EvidenceError(f"{label} amounts must be finite and nonnegative")
