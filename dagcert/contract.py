"""The complete dagcert ontology: workers, tasks, resources, and timings."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence
import json


class ContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Worker:
    id: str
    concurrency: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    capacity: float
    initial: float = 0
    unit: str = "slots"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Timing:
    metric: str
    upper_ms: float | None = None
    lower_ms: float | None = None
    evidence: str = "measured"
    minimum_samples: int = 10
    policy: str = "max"
    percentile: float | None = None
    safety_factor: float = 1.30


@dataclass(frozen=True, slots=True)
class ResourceEffect:
    acquire: float = 0
    consume: float = 0
    produce: float = 0


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    worker: str
    input_type: str
    output_type: str
    depends_on: tuple[str, ...] = ()
    resources: Mapping[str, ResourceEffect] = field(default_factory=dict)
    timings: Mapping[str, Timing] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Contract:
    schema: str
    workers: tuple[Worker, ...]
    tasks: tuple[Task, ...]
    resources: tuple[Resource, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def worker_by_id(self) -> Mapping[str, Worker]:
        return {item.id: item for item in self.workers}

    @property
    def task_by_id(self) -> Mapping[str, Task]:
        return {item.id: item for item in self.tasks}

    @property
    def resource_by_id(self) -> Mapping[str, Resource]:
        return {item.id: item for item in self.resources}

    def topological_tasks(self) -> tuple[str, ...]:
        remaining = {task.id: set(task.depends_on) for task in self.tasks}
        result: list[str] = []
        while remaining:
            ready = sorted(identifier for identifier, dependencies in remaining.items() if not dependencies)
            if not ready:
                raise ContractError("task dependency graph contains a cycle")
            result.extend(ready)
            for identifier in ready:
                remaining.pop(identifier)
            for dependencies in remaining.values():
                dependencies.difference_update(ready)
        return tuple(result)


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{label} must be an array")
    return value


def _positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) <= 0:
        raise ContractError(f"{label} must be positive")
    return float(value)


def _nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) < 0:
        raise ContractError(f"{label} must be nonnegative")
    return float(value)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    result = value.strip()
    if not result:
        raise ContractError(f"{label} is required")
    return result


def _load(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ContractError("YAML contracts require the optional PyYAML dependency") from exc
        value = yaml.safe_load(text)
    return _object(value, "contract")


def load_contract(path: str | Path) -> Contract:
    raw = _load(Path(path))
    if raw.get("schema") != "dagcert-contract/v2":
        raise ContractError("contract schema must be dagcert-contract/v2")

    workers: list[Worker] = []
    for value in _array(raw.get("workers", ()), "workers"):
        row = _object(value, "worker")
        concurrency = _positive(row.get("concurrency"), "worker.concurrency")
        if not concurrency.is_integer():
            raise ContractError("worker.concurrency must be an integer")
        workers.append(Worker(
            _identifier(row.get("id"), "worker.id"), int(concurrency),
            dict(_object(row.get("metadata", {}), "worker.metadata")),
        ))

    resources: list[Resource] = []
    for value in _array(raw.get("resources", ()), "resources"):
        row = _object(value, "resource")
        resources.append(Resource(
            _identifier(row.get("id"), "resource.id"),
            _positive(row.get("capacity"), "resource.capacity"),
            _nonnegative(row.get("initial", 0), "resource.initial"),
            _identifier(row.get("unit", "slots"), "resource.unit"),
            dict(_object(row.get("metadata", {}), "resource.metadata")),
        ))

    tasks: list[Task] = []
    for value in _array(raw.get("tasks", ()), "tasks"):
        row = _object(value, "task")
        task_id = _identifier(row.get("id"), "task.id")
        timing_rows = _object(row.get("timings", {}), f"task {task_id}.timings")
        timings: dict[str, Timing] = {}
        for case, timing_value in timing_rows.items():
            case_id = _identifier(case, f"task {task_id}.timing case")
            timing = _object(timing_value, f"task {task_id}.timings.{case_id}")
            metric = str(timing.get("metric", "duration"))
            if metric not in {"duration", "interval", "wait", "age"}:
                raise ContractError("timing.metric must be duration, interval, wait, or age")
            evidence_kind = str(timing.get("evidence", "measured"))
            if evidence_kind not in {"measured", "assumed"}:
                raise ContractError("timing.evidence must be measured or assumed")
            policy = str(timing.get("policy", "max"))
            percentile = (
                _positive(timing["percentile"], "timing.percentile")
                if timing.get("percentile") is not None else None
            )
            sample_count = _nonnegative(
                timing.get("minimum_samples", 10 if evidence_kind == "measured" else 0),
                "timing.minimum_samples",
            )
            if not sample_count.is_integer():
                raise ContractError("timing.minimum_samples must be an integer")
            minimum_samples = int(sample_count)
            if evidence_kind == "measured" and minimum_samples < 1:
                raise ContractError("measured timing.minimum_samples must be positive")
            if evidence_kind == "assumed" and minimum_samples != 0:
                raise ContractError("assumed timing.minimum_samples must be zero")
            safety_factor = _positive(timing.get("safety_factor", 1.30), "timing.safety_factor")
            if safety_factor < 1:
                raise ContractError("timing.safety_factor must be at least 1")
            if policy not in {"max", "percentile"}:
                raise ContractError("timing.policy must be max or percentile")
            if policy == "max" and percentile is not None:
                raise ContractError("max timing must not declare percentile")
            if policy == "percentile":
                if percentile is None or not 0 < percentile < 100:
                    raise ContractError("percentile timing requires percentile in (0,100)")
                if minimum_samples < ceil(100 / (100 - percentile)):
                    raise ContractError("minimum_samples is too small for the requested percentile")
            upper_ms = _positive(timing["upper_ms"], "timing.upper_ms") if timing.get("upper_ms") is not None else None
            lower_ms = _nonnegative(timing["lower_ms"], "timing.lower_ms") if timing.get("lower_ms") is not None else None
            if upper_ms is None and lower_ms is None:
                raise ContractError("timing requires upper_ms and/or lower_ms")
            if upper_ms is not None and lower_ms is not None and lower_ms >= upper_ms:
                raise ContractError("timing.lower_ms must be less than upper_ms")
            timings[case_id] = Timing(
                metric, upper_ms, lower_ms, evidence_kind, minimum_samples,
                policy, percentile, safety_factor,
            )
        resource_use: dict[str, ResourceEffect] = {}
        for identifier, effect_value in _object(row.get("resources", {}), f"task {task_id}.resources").items():
            resource_id = _identifier(identifier, f"task {task_id}.resource ID")
            effect = _object(effect_value, f"task {task_id}.resources.{resource_id}")
            parsed = ResourceEffect(
                acquire=_nonnegative(effect.get("acquire", 0), "resource effect acquire"),
                consume=_nonnegative(effect.get("consume", 0), "resource effect consume"),
                produce=_nonnegative(effect.get("produce", 0), "resource effect produce"),
            )
            if parsed == ResourceEffect():
                raise ContractError(f"task {task_id}.resources.{resource_id} must have a positive effect")
            resource_use[resource_id] = parsed
        dependencies = tuple(
            _identifier(item, f"task {task_id}.dependency")
            for item in _array(row.get("depends_on", ()), f"task {task_id}.depends_on")
        )
        if len(dependencies) != len(set(dependencies)):
            raise ContractError(f"task {task_id}.depends_on must not contain duplicates")
        tasks.append(Task(
            task_id,
            _identifier(row.get("worker"), f"task {task_id}.worker"),
            _identifier(row.get("input_type"), f"task {task_id}.input_type"),
            _identifier(row.get("output_type"), f"task {task_id}.output_type"),
            dependencies,
            resource_use,
            timings,
            dict(_object(row.get("metadata", {}), f"task {task_id}.metadata")),
        ))

    contract = Contract(
        "dagcert-contract/v2", tuple(workers), tuple(tasks), tuple(resources),
        dict(_object(raw.get("metadata", {}), "metadata")),
    )
    _validate(contract)
    return contract


def _validate(contract: Contract) -> None:
    for label, identifiers in (
        ("worker", [item.id for item in contract.workers]),
        ("task", [item.id for item in contract.tasks]),
        ("resource", [item.id for item in contract.resources]),
    ):
        if label != "resource" and not identifiers:
            raise ContractError(f"contract must declare at least one {label}")
        if len(identifiers) != len(set(identifiers)):
            raise ContractError(f"{label} IDs must be unique")
    workers = contract.worker_by_id
    tasks = contract.task_by_id
    resources = contract.resource_by_id
    for task in contract.tasks:
        if not task.timings:
            raise ContractError(f"task {task.id} must declare at least one timing")
        if not any(timing.metric == "duration" for timing in task.timings.values()):
            raise ContractError(f"task {task.id} must declare a duration timing")
        if task.worker not in workers:
            raise ContractError(f"task {task.id} references unknown worker {task.worker}")
        missing_dependencies = set(task.depends_on) - set(tasks)
        if missing_dependencies:
            raise ContractError(f"task {task.id} has unknown dependencies {sorted(missing_dependencies)}")
        if task.id in task.depends_on:
            raise ContractError(f"task {task.id} depends on itself")
        for resource_id, effect in task.resources.items():
            if resource_id not in resources:
                raise ContractError(f"task {task.id} references unknown resource {resource_id}")
            resource = resources[resource_id]
            if effect.acquire > resource.capacity:
                raise ContractError(f"task {task.id} acquires more {resource_id} than exists")
            if effect.consume > resource.capacity or effect.produce > resource.capacity:
                raise ContractError(f"task {task.id} moves more {resource_id} than its capacity")
    for resource in contract.resources:
        if resource.initial > resource.capacity:
            raise ContractError(f"resource {resource.id} initial amount exceeds capacity")
    contract.topological_tasks()
