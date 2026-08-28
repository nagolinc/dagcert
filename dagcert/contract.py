"""The complete dagcert ontology: workers, tasks, resources, and timings."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence
import json

from .source_types import SourceSignature, SourceTypeError, read_python_signature


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
class Implementation:
    language: str
    path: str
    symbol: str


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    type: str
    resources: Mapping[str, ResourceEffect] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskErrorBudget:
    """Engineering bad-event budget over one canonical task timing stream."""

    basis: str
    evidence_case: str
    good_outcomes: tuple[str, ...]
    bad_event_probability_upper: float
    minimum_observations: int


@dataclass(frozen=True, slots=True)
class TypedDependency:
    task: str
    outcome_type: str


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
    role: str = "operation"
    implementation: Implementation | None = None
    outcomes: tuple[TaskOutcome, ...] = ()
    source_signature: SourceSignature | None = None
    typed_dependencies: tuple[TypedDependency, ...] = ()
    error_budget: TaskErrorBudget | None = None

    @property
    def outcome_by_type(self) -> Mapping[str, TaskOutcome]:
        return {item.type: item for item in self.outcomes}

    def guaranteed_effect(self, resource_id: str, kind: str) -> float:
        """Return the minimum effect across the complete source-declared outcome union."""
        if not self.outcomes:
            effect = self.resources.get(resource_id, ResourceEffect())
            return float(getattr(effect, kind))
        return min(
            float(getattr(outcome.resources.get(resource_id, ResourceEffect()), kind))
            for outcome in self.outcomes
        )

    def possible_effect(self, resource_id: str, kind: str) -> float:
        """Return the largest effect on any source-declared outcome branch."""
        if not self.outcomes:
            effect = self.resources.get(resource_id, ResourceEffect())
            return float(getattr(effect, kind))
        return max(
            float(getattr(outcome.resources.get(resource_id, ResourceEffect()), kind))
            for outcome in self.outcomes
        )


@dataclass(frozen=True, slots=True)
class CompositionStep:
    task: str
    timing: str
    count: int = 1
    outcome_type: str | None = None


@dataclass(frozen=True, slots=True)
class Composition:
    """A finite application path whose bound is derived from real operation tasks."""

    id: str
    steps: tuple[CompositionStep, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def task_refs(self) -> tuple[str, ...]:
        return tuple(step.task for step in self.steps)


@dataclass(frozen=True, slots=True)
class Contract:
    schema: str
    workers: tuple[Worker, ...]
    tasks: tuple[Task, ...]
    resources: tuple[Resource, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    compositions: tuple[Composition, ...] = ()

    @property
    def worker_by_id(self) -> Mapping[str, Worker]:
        return {item.id: item for item in self.workers}

    @property
    def task_by_id(self) -> Mapping[str, Task]:
        return {item.id: item for item in self.tasks}

    @property
    def resource_by_id(self) -> Mapping[str, Resource]:
        return {item.id: item for item in self.resources}

    @property
    def composition_by_id(self) -> Mapping[str, Composition]:
        return {item.id: item for item in self.compositions}

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


def _probability(value: Any, label: str) -> float:
    result = _nonnegative(value, label)
    if result >= 1:
        raise ContractError(f"{label} must be less than 1")
    return result


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


def load_contract(path: str | Path, *, source_root: str | Path | None = None) -> Contract:
    contract_path = Path(path)
    raw = _load(contract_path)
    schema = raw.get("schema")
    if schema not in {
        "dagcert-contract/v2", "dagcert-contract/v3", "dagcert-contract/v4",
        "dagcert-contract/v5",
    }:
        raise ContractError("contract schema must be dagcert-contract/v2, v3, v4, or v5")
    if schema in {"dagcert-contract/v3", "dagcert-contract/v4", "dagcert-contract/v5"} and set(raw) != {
        "schema", "workers", "resources", "tasks", "compositions", "metadata",
    }:
        raise ContractError(
            f"{schema.rsplit('/', 1)[-1]} contract must contain exactly schema, workers, resources, "
            "tasks, compositions, and metadata"
        )
    implementation_root = Path(source_root).resolve() if source_root is not None else contract_path.resolve().parent

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
        legacy_task_fields = {
            "id", "role", "worker", "input_type", "output_type", "depends_on",
            "resources", "timings",
        }
        v4_task_fields = {
            "id", "role", "worker", "implementation", "outcomes", "depends_on", "timings",
        }
        v5_task_fields = v4_task_fields | {"error_budget"}
        allowed_task_fields = (
            v5_task_fields if schema == "dagcert-contract/v5"
            else v4_task_fields if schema == "dagcert-contract/v4"
            else legacy_task_fields
        )
        unexpected_task_fields = set(row) - (allowed_task_fields | {"metadata"})
        if schema == "dagcert-contract/v3" and unexpected_task_fields:
            raise ContractError(
                f"v3 task contains unexpected fields {sorted(unexpected_task_fields)}"
            )
        if schema == "dagcert-contract/v4" and (unexpected_task_fields or set(row) - {"metadata"} != v4_task_fields):
            missing = sorted(v4_task_fields - set(row))
            raise ContractError(
                f"v4 task fields mismatch: unexpected={sorted(unexpected_task_fields)}, missing={missing}"
            )
        if schema == "dagcert-contract/v5" and (unexpected_task_fields or set(row) - {"metadata"} != v5_task_fields):
            missing = sorted(v5_task_fields - set(row))
            raise ContractError(
                f"v5 task fields mismatch: unexpected={sorted(unexpected_task_fields)}, missing={missing}"
            )
        task_id = _identifier(row.get("id"), "task.id")
        role = _identifier(
            row.get("role") if schema in {"dagcert-contract/v3", "dagcert-contract/v4", "dagcert-contract/v5"} else row.get("role", "operation"),
            f"task {task_id}.role",
        )
        if schema in {"dagcert-contract/v3", "dagcert-contract/v4", "dagcert-contract/v5"} and role not in {"operation", "instrumentation"}:
            raise ContractError(f"task {task_id}.role must be operation or instrumentation")
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
        def parse_effects(value: Any, label: str) -> dict[str, ResourceEffect]:
            resource_use: dict[str, ResourceEffect] = {}
            for identifier, effect_value in _object(value, label).items():
                resource_id = _identifier(identifier, f"{label} resource ID")
                effect = _object(effect_value, f"{label}.{resource_id}")
                parsed = ResourceEffect(
                    acquire=_nonnegative(effect.get("acquire", 0), "resource effect acquire"),
                    consume=_nonnegative(effect.get("consume", 0), "resource effect consume"),
                    produce=_nonnegative(effect.get("produce", 0), "resource effect produce"),
                )
                if set(effect) - {"acquire", "consume", "produce"}:
                    raise ContractError(f"{label}.{resource_id} contains unexpected fields")
                if parsed == ResourceEffect():
                    raise ContractError(f"{label}.{resource_id} must have a positive effect")
                resource_use[resource_id] = parsed
            return resource_use

        implementation: Implementation | None = None
        outcomes: tuple[TaskOutcome, ...] = ()
        source_signature: SourceSignature | None = None
        if schema in {"dagcert-contract/v4", "dagcert-contract/v5"}:
            binding = _object(row.get("implementation"), f"task {task_id}.implementation")
            if set(binding) != {"language", "path", "symbol"}:
                raise ContractError(
                    f"task {task_id}.implementation must contain exactly language, path, and symbol"
                )
            implementation = Implementation(
                _identifier(binding.get("language"), f"task {task_id}.implementation.language"),
                _identifier(binding.get("path"), f"task {task_id}.implementation.path"),
                _identifier(binding.get("symbol"), f"task {task_id}.implementation.symbol"),
            )
            if implementation.language != "python":
                raise ContractError(
                    f"task {task_id} uses unsupported source type provider {implementation.language!r}"
                )
            try:
                source_signature = read_python_signature(
                    implementation_root, implementation.path, implementation.symbol,
                    include_legacy_unhandled=schema == "dagcert-contract/v4",
                )
            except SourceTypeError as exc:
                raise ContractError(f"task {task_id} source type error: {exc}") from exc
            outcome_rows = _array(row.get("outcomes"), f"task {task_id}.outcomes")
            parsed_outcomes: list[TaskOutcome] = []
            for outcome_value in outcome_rows:
                outcome = _object(outcome_value, f"task {task_id}.outcome")
                if set(outcome) != {"type", "resources", "metadata"}:
                    raise ContractError(
                        f"task {task_id} outcome must contain exactly type, resources, and metadata"
                    )
                parsed_outcomes.append(TaskOutcome(
                    _identifier(outcome.get("type"), f"task {task_id}.outcome.type"),
                    parse_effects(outcome.get("resources"), f"task {task_id}.outcome.resources"),
                    dict(_object(outcome.get("metadata"), f"task {task_id}.outcome.metadata")),
                ))
            declared_types = tuple(item.type for item in parsed_outcomes)
            if len(declared_types) != len(set(declared_types)):
                raise ContractError(f"task {task_id} outcome types must be unique")
            if set(declared_types) != set(source_signature.outcome_types):
                raise ContractError(
                    f"task {task_id} outcomes do not exactly match source return union: "
                    f"source={list(source_signature.outcome_types)}, contract={list(declared_types)}"
                )
            if schema == "dagcert-contract/v4":
                unhandled = next(
                    item for item in parsed_outcomes
                    if item.type == "dagcert.runtime.UnhandledException"
                )
                if unhandled.resources:
                    raise ContractError(
                        f"task {task_id} cannot assign resource effects to the legacy "
                        "UnhandledException outcome; catch and return an explicit typed recovery "
                        "outcome after performing cleanup"
                    )
            outcomes = tuple(parsed_outcomes)
            input_type = source_signature.input_type
            output_type = " | ".join(source_signature.outcome_types)
            resource_ids = {identifier for outcome in outcomes for identifier in outcome.resources}
            resource_use = {
                identifier: ResourceEffect(
                    acquire=max(outcome.resources.get(identifier, ResourceEffect()).acquire for outcome in outcomes),
                    consume=max(outcome.resources.get(identifier, ResourceEffect()).consume for outcome in outcomes),
                    produce=max(outcome.resources.get(identifier, ResourceEffect()).produce for outcome in outcomes),
                )
                for identifier in resource_ids
            }
        else:
            resource_use = parse_effects(row.get("resources", {}), f"task {task_id}.resources")
            input_type = _identifier(row.get("input_type"), f"task {task_id}.input_type")
            output_type = _identifier(row.get("output_type"), f"task {task_id}.output_type")
        error_budget: TaskErrorBudget | None = None
        if schema == "dagcert-contract/v5" and row.get("error_budget") is not None:
            budget = _object(row.get("error_budget"), f"task {task_id}.error_budget")
            required_budget_fields = {
                "basis", "evidence_case", "good_outcomes",
                "bad_event_probability_upper", "minimum_observations",
            }
            if set(budget) != required_budget_fields:
                raise ContractError(
                    f"task {task_id}.error_budget must contain exactly "
                    f"{sorted(required_budget_fields)}"
                )
            basis = _identifier(budget.get("basis"), f"task {task_id}.error_budget.basis")
            if basis != "engineering_assumption":
                raise ContractError(
                    f"task {task_id}.error_budget.basis must be engineering_assumption"
                )
            good_outcomes = tuple(
                _identifier(item, f"task {task_id}.error_budget.good_outcomes")
                for item in _array(
                    budget.get("good_outcomes"),
                    f"task {task_id}.error_budget.good_outcomes",
                )
            )
            if not good_outcomes or len(good_outcomes) != len(set(good_outcomes)):
                raise ContractError(
                    f"task {task_id}.error_budget.good_outcomes must be nonempty and unique"
                )
            observation_count = _positive(
                budget.get("minimum_observations"),
                f"task {task_id}.error_budget.minimum_observations",
            )
            if not observation_count.is_integer():
                raise ContractError(
                    f"task {task_id}.error_budget.minimum_observations must be an integer"
                )
            error_budget = TaskErrorBudget(
                basis,
                _identifier(
                    budget.get("evidence_case"),
                    f"task {task_id}.error_budget.evidence_case",
                ),
                good_outcomes,
                _probability(
                    budget.get("bad_event_probability_upper"),
                    f"task {task_id}.error_budget.bad_event_probability_upper",
                ),
                int(observation_count),
            )
        typed_dependencies: tuple[TypedDependency, ...] = ()
        dependency_values = _array(row.get("depends_on", ()), f"task {task_id}.depends_on")
        if schema in {"dagcert-contract/v4", "dagcert-contract/v5"}:
            parsed_dependencies: list[TypedDependency] = []
            for dependency_value in dependency_values:
                dependency = _object(dependency_value, f"task {task_id}.dependency")
                if set(dependency) != {"task", "outcome_type"}:
                    raise ContractError(
                        f"task {task_id} typed dependency must contain exactly task and outcome_type"
                    )
                parsed_dependencies.append(TypedDependency(
                    _identifier(dependency.get("task"), f"task {task_id}.dependency.task"),
                    _identifier(
                        dependency.get("outcome_type"),
                        f"task {task_id}.dependency.outcome_type",
                    ),
                ))
            typed_dependencies = tuple(parsed_dependencies)
            dependencies = tuple(item.task for item in typed_dependencies)
        else:
            dependencies = tuple(
                _identifier(item, f"task {task_id}.dependency")
                for item in dependency_values
            )
        if len(dependencies) != len(set(dependencies)):
            raise ContractError(f"task {task_id}.depends_on must not contain duplicates")
        tasks.append(Task(
            task_id,
            _identifier(row.get("worker"), f"task {task_id}.worker"),
            input_type,
            output_type,
            dependencies,
            resource_use,
            timings,
            dict(_object(row.get("metadata", {}), f"task {task_id}.metadata")),
            role,
            implementation,
            outcomes,
            source_signature,
            typed_dependencies,
            error_budget,
        ))

    compositions: list[Composition] = []
    for value in _array(raw.get("compositions", ()), "compositions"):
        row = _object(value, "composition")
        if set(row) != {"id", "steps", "metadata"}:
            raise ContractError("composition must contain exactly id, steps, and metadata")
        composition_id = _identifier(row.get("id"), "composition.id")
        steps: list[CompositionStep] = []
        for step_value in _array(row.get("steps"), f"composition {composition_id}.steps"):
            step = _object(step_value, f"composition {composition_id}.step")
            required_step_fields = (
                {"task", "timing", "count", "outcome_type"}
                if schema in {"dagcert-contract/v4", "dagcert-contract/v5"}
                else {"task", "timing", "count"}
            )
            if set(step) != required_step_fields:
                suffix = ", and outcome_type" if schema in {"dagcert-contract/v4", "dagcert-contract/v5"} else ""
                raise ContractError(
                    "composition step must contain exactly task, timing, count" + suffix
                )
            count = _positive(step.get("count"), "composition step count")
            if not count.is_integer():
                raise ContractError("composition step count must be an integer")
            steps.append(CompositionStep(
                _identifier(step.get("task"), f"composition {composition_id}.step.task"),
                _identifier(step.get("timing"), f"composition {composition_id}.step.timing"),
                int(count),
                _identifier(
                    step.get("outcome_type"),
                    f"composition {composition_id}.step.outcome_type",
                ) if schema in {"dagcert-contract/v4", "dagcert-contract/v5"} else None,
            ))
        task_refs = tuple(step.task for step in steps)
        if len(set(task_refs)) < 2:
            raise ContractError(f"composition {composition_id} must contain at least two operation tasks")
        if len(task_refs) != len(set(task_refs)):
            raise ContractError(
                f"composition {composition_id} must combine repeated executions with step.count"
            )
        compositions.append(Composition(
            composition_id,
            tuple(steps),
            dict(_object(row.get("metadata", {}), f"composition {composition_id}.metadata")),
        ))

    contract = Contract(
        str(schema), tuple(workers), tuple(tasks), tuple(resources),
        dict(_object(raw.get("metadata", {}), "metadata")),
        tuple(compositions),
    )
    _validate(contract)
    return contract


def _validate(contract: Contract) -> None:
    for label, identifiers in (
        ("worker", [item.id for item in contract.workers]),
        ("task", [item.id for item in contract.tasks]),
        ("resource", [item.id for item in contract.resources]),
        ("composition", [item.id for item in contract.compositions]),
    ):
        if label not in {"resource", "composition"} and not identifiers:
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
        if contract.schema in {"dagcert-contract/v4", "dagcert-contract/v5"}:
            for dependency in task.typed_dependencies:
                upstream = tasks.get(dependency.task)
                if upstream is None:
                    continue
                if dependency.outcome_type not in upstream.outcome_by_type:
                    raise ContractError(
                        f"task {task.id} dependency cites {dependency.task} outcome "
                        f"{dependency.outcome_type!r}, which is not in the upstream source union"
                    )
                if dependency.outcome_type != task.input_type:
                    raise ContractError(
                        f"task {task.id} source input {task.input_type!r} does not accept typed edge "
                        f"{dependency.task}/{dependency.outcome_type}"
                    )
            if contract.schema == "dagcert-contract/v5" and task.error_budget is not None:
                budget = task.error_budget
                unknown_good = set(budget.good_outcomes) - set(task.outcome_by_type)
                if unknown_good:
                    raise ContractError(
                        f"task {task.id}.error_budget cites unknown good outcomes "
                        f"{sorted(unknown_good)}"
                    )
                if budget.evidence_case not in task.timings:
                    raise ContractError(
                        f"task {task.id}.error_budget cites unknown evidence case "
                        f"{budget.evidence_case!r}"
                    )
                if task.timings[budget.evidence_case].metric != "duration":
                    raise ContractError(
                        f"task {task.id}.error_budget evidence case must be a duration timing"
                    )
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
    for composition in contract.compositions:
        unknown = set(composition.task_refs) - set(tasks)
        if unknown:
            raise ContractError(
                f"composition {composition.id} references unknown tasks {sorted(unknown)}"
            )
        instrumentation = sorted(
            task_id for task_id in composition.task_refs
            if tasks[task_id].role != "operation"
        )
        if instrumentation:
            raise ContractError(
                f"composition {composition.id} cannot use instrumentation tasks {instrumentation}"
            )
        for step in composition.steps:
            task = tasks[step.task]
            timing = task.timings.get(step.timing)
            if timing is None:
                raise ContractError(
                    f"composition {composition.id} cites unknown timing {step.task}/{step.timing}"
                )
            if timing.metric != "duration":
                raise ContractError(
                    f"composition {composition.id} step {step.task}/{step.timing} must be a duration"
                )
            if contract.schema in {"dagcert-contract/v4", "dagcert-contract/v5"}:
                if step.outcome_type not in task.outcome_by_type:
                    raise ContractError(
                        f"composition {composition.id} step {step.task} cites outcome "
                        f"{step.outcome_type!r} outside the task's source union"
                    )
                if step.count > 1 and step.outcome_type != task.input_type:
                    raise ContractError(
                        f"composition {composition.id} repeats {step.task}, but outcome "
                        f"{step.outcome_type!r} is not the task input {task.input_type!r}"
                    )
        if contract.schema in {"dagcert-contract/v4", "dagcert-contract/v5"}:
            for upstream_step, downstream_step in zip(
                composition.steps, composition.steps[1:], strict=False,
            ):
                downstream = tasks[downstream_step.task]
                typed_edge = TypedDependency(upstream_step.task, str(upstream_step.outcome_type))
                if typed_edge not in downstream.typed_dependencies:
                    raise ContractError(
                        f"composition {composition.id} is not a real typed path: "
                        f"{upstream_step.task}/{upstream_step.outcome_type} does not feed "
                        f"{downstream_step.task}/{downstream.input_type}"
                    )
        selected = set(composition.task_refs)
        connected = {composition.task_refs[0]}
        changed = True
        while changed:
            changed = False
            for task_id in selected - connected:
                dependencies = set(tasks[task_id].depends_on) & selected
                dependents = {
                    candidate.id for candidate in contract.tasks
                    if task_id in candidate.depends_on and candidate.id in selected
                }
                resource_neighbors = {
                    candidate.id for candidate in contract.tasks
                    if candidate.id in selected
                    and set(tasks[task_id].resources) & set(candidate.resources)
                }
                if (dependencies | dependents | resource_neighbors) & connected:
                    connected.add(task_id)
                    changed = True
        if connected != selected:
            raise ContractError(
                f"composition {composition.id} tasks must form one connected DAG subgraph"
            )
    contract.topological_tasks()
