"""The complete dagcert ontology: workers, tasks, resources, and timings."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import keyword

from .source_types import (
    SourceSignature, SourceTypeError, read_python_signature, validate_external_contract_stub,
)


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
class ExternalProvider:
    """The real library surface assumed by an external task."""

    module: str
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExternalContract:
    """A visible Nagini assumption plus runtime conformance boundary."""

    stub_path: str
    assumption: str
    provider: ExternalProvider
    success_outcome: str
    evidence_case: str


@dataclass(frozen=True, slots=True)
class SourceCallableProvider:
    """A source-owned concrete value supplied to one callable operation-input field."""

    path: str
    symbol: str


@dataclass(frozen=True, slots=True)
class ExternalCallableProvider:
    """A callable supplied by one explicit checked external overlay."""

    module: str
    symbol: str
    stub_path: str
    exception_policy: str


@dataclass(frozen=True, slots=True)
class CallableBinding:
    """Concrete provenance for one callable-valued operation-input field."""

    id: str
    field: str
    provider: SourceCallableProvider | ExternalCallableProvider


@dataclass(frozen=True, slots=True)
class TypedDependency:
    task: str
    outcome_type: str
    input_field: str | None = None


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
    external_contract: ExternalContract | None = None
    callable_bindings: tuple[CallableBinding, ...] = ()
    start_resources: Mapping[str, ResourceEffect] = field(default_factory=dict)

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
class CompositionExpression:
    """One node in the deliberately small structured-workflow algebra."""

    kind: str
    step: CompositionStep | None = None
    children: tuple[CompositionExpression, ...] = ()
    count: int = 1


@dataclass(frozen=True, slots=True)
class Composition:
    """A finite application path whose bound is derived from real operation tasks."""

    id: str
    steps: tuple[CompositionStep, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    expression: CompositionExpression | None = None

    @property
    def task_refs(self) -> tuple[str, ...]:
        return tuple(step.task for step in self.steps)


@dataclass(frozen=True, slots=True)
class StateClaim:
    """One kernel-owned restricted lifecycle or bounded-flow proof request."""

    id: str
    kind: str
    specification: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Contract:
    schema: str
    workers: tuple[Worker, ...]
    tasks: tuple[Task, ...]
    resources: tuple[Resource, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    compositions: tuple[Composition, ...] = ()
    state_claims: tuple[StateClaim, ...] = ()

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

    @property
    def state_claim_by_id(self) -> Mapping[str, StateClaim]:
        return {item.id: item for item in self.state_claims}

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


def composition_steps(
    expression: CompositionExpression, *, multiplier: int = 1,
) -> tuple[CompositionStep, ...]:
    """Flatten a structured expression only for coverage and union-bound accounting."""

    if expression.kind == "leaf":
        assert expression.step is not None
        step = expression.step
        return (
            CompositionStep(
                step.task, step.timing, step.count * multiplier, step.outcome_type,
            ),
        )
    if expression.kind == "finite_repeat":
        return composition_steps(
            expression.children[0], multiplier=multiplier * expression.count,
        )
    result: list[CompositionStep] = []
    for child in expression.children:
        result.extend(composition_steps(child, multiplier=multiplier))
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


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a finite number")
    result = float(value)
    if not isfinite(result):
        raise ContractError(f"{label} must be a finite number")
    return result


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


def _python_identifier(value: Any, label: str) -> str:
    result = _identifier(value, label)
    if not result.isidentifier() or keyword.iskeyword(result):
        raise ContractError(f"{label} must be a Python identifier")
    return result


def _composition_expression(value: Any, label: str) -> CompositionExpression:
    row = _object(value, label)
    kind = _identifier(row.get("kind"), f"{label}.kind")
    if kind == "leaf":
        required = {"kind", "task", "timing", "outcome_type"}
        if set(row) != required:
            raise ContractError(
                f"{label} leaf must contain exactly kind, task, timing, and outcome_type"
            )
        return CompositionExpression(
            "leaf",
            step=CompositionStep(
                _identifier(row.get("task"), f"{label}.task"),
                _identifier(row.get("timing"), f"{label}.timing"),
                1,
                _identifier(row.get("outcome_type"), f"{label}.outcome_type"),
            ),
        )
    if kind in {"sequence", "parallel_all"}:
        if set(row) != {"kind", "children"}:
            raise ContractError(f"{label} {kind} must contain exactly kind and children")
        raw_children = _array(row.get("children"), f"{label}.children")
        if len(raw_children) < 2:
            raise ContractError(f"{label} {kind} requires at least two children")
        return CompositionExpression(
            kind,
            children=tuple(
                _composition_expression(child, f"{label}.children[{index}]")
                for index, child in enumerate(raw_children)
            ),
        )
    if kind == "finite_repeat":
        if set(row) != {"kind", "count", "body"}:
            raise ContractError(
                f"{label} finite_repeat must contain exactly kind, count, and body"
            )
        count = _positive(row.get("count"), f"{label}.count")
        if not count.is_integer():
            raise ContractError(f"{label}.count must be an integer")
        return CompositionExpression(
            kind,
            children=(_composition_expression(row.get("body"), f"{label}.body"),),
            count=int(count),
        )
    raise ContractError(
        f"{label}.kind must be leaf, sequence, parallel_all, or finite_repeat"
    )


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
        "dagcert-contract/v5", "dagcert-contract/v6", "dagcert-contract/v7",
    }:
        raise ContractError(
            "contract schema must be dagcert-contract/v2, v3, v4, v5, v6, or v7"
        )
    expected_top_level = {
        "schema", "workers", "resources", "tasks", "compositions", "metadata",
    }
    if schema == "dagcert-contract/v7":
        expected_top_level.add("state_claims")
    if schema in {
        "dagcert-contract/v3", "dagcert-contract/v4", "dagcert-contract/v5",
        "dagcert-contract/v6", "dagcert-contract/v7",
    } and set(raw) != expected_top_level:
        raise ContractError(
            f"{schema.rsplit('/', 1)[-1]} contract must contain exactly schema, workers, resources, "
            "tasks, compositions, metadata, and state_claims for v7"
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
        v6_task_fields = v5_task_fields | {"external_contract"}
        v6_optional_task_fields = {"callable_bindings"}
        v7_task_fields = v6_task_fields | {"start_resources"}
        v7_optional_task_fields = v6_optional_task_fields | {"verified_interface"}
        allowed_task_fields = (
            v7_task_fields | v7_optional_task_fields if schema == "dagcert-contract/v7"
            else v6_task_fields | v6_optional_task_fields if schema == "dagcert-contract/v6"
            else v5_task_fields if schema == "dagcert-contract/v5"
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
        if schema == "dagcert-contract/v6" and (
            unexpected_task_fields or v6_task_fields - (set(row) - {"metadata"})
        ):
            missing = sorted(v6_task_fields - set(row))
            raise ContractError(
                f"v6 task fields mismatch: unexpected={sorted(unexpected_task_fields)}, missing={missing}"
            )
        if schema == "dagcert-contract/v7" and (
            unexpected_task_fields or v7_task_fields - (set(row) - {"metadata"})
        ):
            missing = sorted(v7_task_fields - set(row))
            raise ContractError(
                f"v7 task fields mismatch: unexpected={sorted(unexpected_task_fields)}, "
                f"missing={missing}"
            )
        task_id = _identifier(row.get("id"), "task.id")
        role = _identifier(
            row.get("role") if schema in {
                "dagcert-contract/v3", "dagcert-contract/v4", "dagcert-contract/v5",
                "dagcert-contract/v6", "dagcert-contract/v7",
            } else row.get("role", "operation"),
            f"task {task_id}.role",
        )
        allowed_roles = (
            {"operation", "instrumentation", "external"}
            if schema in {"dagcert-contract/v6", "dagcert-contract/v7"}
            else {"operation", "instrumentation"}
        )
        if schema in {
            "dagcert-contract/v3", "dagcert-contract/v4", "dagcert-contract/v5",
            "dagcert-contract/v6", "dagcert-contract/v7",
        } and role not in allowed_roles:
            raise ContractError(
                f"task {task_id}.role must be one of {sorted(allowed_roles)}"
            )
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
        external_contract: ExternalContract | None = None
        callable_bindings: tuple[CallableBinding, ...] = ()
        if schema in {"dagcert-contract/v6", "dagcert-contract/v7"} and row.get("external_contract") is not None:
            external = _object(
                row.get("external_contract"), f"task {task_id}.external_contract"
            )
            if set(external) != {
                "stub_path", "assumption", "provider", "success_outcome", "evidence_case",
            }:
                raise ContractError(
                    f"task {task_id}.external_contract must contain exactly assumption, "
                    "evidence_case, provider, stub_path, and success_outcome"
                )
            provider = _object(
                external.get("provider"), f"task {task_id}.external_contract.provider"
            )
            if set(provider) != {"module", "symbols"}:
                raise ContractError(
                    f"task {task_id}.external_contract.provider must contain module and symbols"
                )
            provider_symbols = tuple(
                _identifier(item, f"task {task_id}.external_contract.provider.symbols")
                for item in _array(
                    provider.get("symbols"),
                    f"task {task_id}.external_contract.provider.symbols",
                )
            )
            if not provider_symbols or len(provider_symbols) != len(set(provider_symbols)):
                raise ContractError(
                    f"task {task_id}.external_contract.provider.symbols must be nonempty and unique"
                )
            external_contract = ExternalContract(
                _identifier(
                    external.get("stub_path"),
                    f"task {task_id}.external_contract.stub_path",
                ),
                _identifier(
                    external.get("assumption"),
                    f"task {task_id}.external_contract.assumption",
                ),
                ExternalProvider(
                    _identifier(
                        provider.get("module"),
                        f"task {task_id}.external_contract.provider.module",
                    ),
                    provider_symbols,
                ),
                _identifier(
                    external.get("success_outcome"),
                    f"task {task_id}.external_contract.success_outcome",
                ),
                _identifier(
                    external.get("evidence_case"),
                    f"task {task_id}.external_contract.evidence_case",
                ),
            )
        if role == "external" and external_contract is None:
            raise ContractError(f"external task {task_id} requires external_contract")
        if role != "external" and external_contract is not None:
            raise ContractError(
                f"non-external task {task_id} must set external_contract to null"
            )
        if schema in {"dagcert-contract/v6", "dagcert-contract/v7"}:
            parsed_bindings: list[CallableBinding] = []
            for binding_value in _array(
                row.get("callable_bindings", ()), f"task {task_id}.callable_bindings"
            ):
                callable_binding = _object(
                    binding_value, f"task {task_id}.callable_binding"
                )
                if set(callable_binding) != {"id", "field", "provider"}:
                    raise ContractError(
                        f"task {task_id}.callable_binding must contain exactly id, field, "
                        "and provider"
                    )
                provider_value = _object(
                    callable_binding.get("provider"),
                    f"task {task_id}.callable_binding.provider",
                )
                provider_kind = _identifier(
                    provider_value.get("kind"),
                    f"task {task_id}.callable_binding.provider.kind",
                )
                if provider_kind == "source":
                    if set(provider_value) != {"kind", "path", "symbol"}:
                        raise ContractError(
                            f"task {task_id} source callable provider must contain exactly "
                            "kind, path, and symbol"
                        )
                    callable_provider: (
                        SourceCallableProvider | ExternalCallableProvider
                    ) = (
                        SourceCallableProvider(
                            _identifier(
                                provider_value.get("path"),
                                f"task {task_id}.callable_binding.provider.path",
                            ),
                            _python_identifier(
                                provider_value.get("symbol"),
                                f"task {task_id}.callable_binding.provider.symbol",
                            ),
                        )
                    )
                elif provider_kind == "external-contract":
                    if set(provider_value) != {
                        "kind", "module", "symbol", "stub_path", "exception_policy",
                    }:
                        raise ContractError(
                            f"task {task_id} external callable provider must contain exactly "
                            "exception_policy, kind, module, stub_path, and symbol"
                        )
                    exception_policy = _identifier(
                        provider_value.get("exception_policy"),
                        f"task {task_id}.callable_binding.provider.exception_policy",
                    )
                    if exception_policy not in {
                        "assume-no-exception", "declared-by-exsures",
                    }:
                        raise ContractError(
                            f"task {task_id} external callable provider exception_policy must "
                            "be assume-no-exception or declared-by-exsures"
                        )
                    callable_provider = ExternalCallableProvider(
                        _identifier(
                            provider_value.get("module"),
                            f"task {task_id}.callable_binding.provider.module",
                        ),
                        _python_identifier(
                            provider_value.get("symbol"),
                            f"task {task_id}.callable_binding.provider.symbol",
                        ),
                        _identifier(
                            provider_value.get("stub_path"),
                            f"task {task_id}.callable_binding.provider.stub_path",
                        ),
                        exception_policy,
                    )
                else:
                    raise ContractError(
                        f"task {task_id} callable provider kind must be source or "
                        "external-contract"
                    )
                parsed_bindings.append(CallableBinding(
                    _identifier(
                        callable_binding.get("id"),
                        f"task {task_id}.callable_binding.id",
                    ),
                    _python_identifier(
                        callable_binding.get("field"),
                        f"task {task_id}.callable_binding.field",
                    ),
                    callable_provider,
                ))
            callable_bindings = tuple(parsed_bindings)
        if schema in {
            "dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6",
            "dagcert-contract/v7",
        }:
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
            if implementation.language == "python":
                if row.get("verified_interface") is not None:
                    raise ContractError(
                        f"task {task_id} Python interface is extracted from source and must not "
                        "declare verified_interface"
                    )
                try:
                    source_signature = read_python_signature(
                        implementation_root, implementation.path, implementation.symbol,
                        include_legacy_unhandled=schema == "dagcert-contract/v4",
                        external_boundary_id=task_id if role == "external" else None,
                    )
                    if external_contract is not None:
                        if source_signature.outcome_types[0] != external_contract.success_outcome:
                            raise SourceTypeError(
                                f"external contract success outcome "
                                f"{external_contract.success_outcome!r} does not match adapter "
                                f"return {source_signature.outcome_types[0]!r}"
                            )
                        validate_external_contract_stub(
                            implementation_root,
                            external_contract.stub_path,
                            implementation.symbol,
                            source_signature,
                        )
                except SourceTypeError as exc:
                    raise ContractError(f"task {task_id} source type error: {exc}") from exc
            elif (
                schema == "dagcert-contract/v7"
                and implementation.language in {"javascript", "typescript"}
            ):
                if role != "operation":
                    raise ContractError(
                        f"task {task_id} verified {implementation.language} leaf must have role "
                        "operation"
                    )
                interface = _object(
                    row.get("verified_interface"), f"task {task_id}.verified_interface",
                )
                if set(interface) != {"execution", "parameters", "return_type"}:
                    raise ContractError(
                        f"task {task_id}.verified_interface must contain execution, parameters, "
                        "and return_type"
                    )
                if interface.get("execution") != "synchronous":
                    raise ContractError(
                        f"task {task_id}.verified_interface currently requires synchronous "
                        "execution"
                    )
                parameter_rows = _array(
                    interface.get("parameters"),
                    f"task {task_id}.verified_interface.parameters",
                )
                if len(parameter_rows) != 1:
                    raise ContractError(
                        f"task {task_id}.verified_interface requires exactly one parameter"
                    )
                parameter = _object(
                    parameter_rows[0],
                    f"task {task_id}.verified_interface.parameters[0]",
                )
                if set(parameter) != {"name", "type"}:
                    raise ContractError(
                        f"task {task_id}.verified_interface parameter must contain name and type"
                    )
                parameter_name = _identifier(
                    parameter.get("name"),
                    f"task {task_id}.verified_interface parameter name",
                )
                parameter_type = _identifier(
                    parameter.get("type"),
                    f"task {task_id}.verified_interface parameter type",
                )
                return_type = _identifier(
                    interface.get("return_type"),
                    f"task {task_id}.verified_interface.return_type",
                )
                allowed_types = {"boolean", "number", "string"}
                if parameter_type not in allowed_types or return_type not in allowed_types:
                    raise ContractError(
                        f"task {task_id}.verified_interface currently supports only primitive "
                        f"types {sorted(allowed_types)}"
                    )
                source_signature = SourceSignature(
                    implementation.language,
                    Path(implementation.path).as_posix(),
                    implementation.symbol,
                    parameter_type,
                    (return_type,),
                    1,
                    ((parameter_name, parameter_type),),
                )
            else:
                raise ContractError(
                    f"task {task_id} uses unsupported source type provider "
                    f"{implementation.language!r}"
                )
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
        if schema in {"dagcert-contract/v5", "dagcert-contract/v6", "dagcert-contract/v7"} and row.get("error_budget") is not None:
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
        if schema in {
            "dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6",
            "dagcert-contract/v7",
        }:
            parsed_dependencies: list[TypedDependency] = []
            for dependency_value in dependency_values:
                dependency = _object(dependency_value, f"task {task_id}.dependency")
                allowed_dependency_fields = (
                    {"task", "outcome_type", "input_field"}
                    if schema == "dagcert-contract/v7"
                    else {"task", "outcome_type"}
                )
                if set(dependency) not in (
                    {"task", "outcome_type"}, allowed_dependency_fields,
                ):
                    raise ContractError(
                        f"task {task_id} typed dependency must contain task, outcome_type, "
                        "and optionally input_field in v7"
                    )
                parsed_dependencies.append(TypedDependency(
                    _identifier(dependency.get("task"), f"task {task_id}.dependency.task"),
                    _identifier(
                        dependency.get("outcome_type"),
                        f"task {task_id}.dependency.outcome_type",
                    ),
                    _python_identifier(
                        dependency.get("input_field"),
                        f"task {task_id}.dependency.input_field",
                    ) if dependency.get("input_field") is not None else None,
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
        start_resources = (
            parse_effects(
                row.get("start_resources", {}), f"task {task_id}.start_resources",
            )
            if schema == "dagcert-contract/v7"
            else {}
        )
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
            external_contract,
            callable_bindings,
            start_resources,
        ))

    compositions: list[Composition] = []
    for value in _array(raw.get("compositions", ()), "compositions"):
        row = _object(value, "composition")
        if schema == "dagcert-contract/v7":
            if set(row) != {"id", "expression", "metadata"}:
                raise ContractError(
                    "v7 composition must contain exactly id, expression, and metadata"
                )
            composition_id = _identifier(row.get("id"), "composition.id")
            expression = _composition_expression(
                row.get("expression"), f"composition {composition_id}.expression",
            )
            v7_steps = composition_steps(expression)
            if len({step.task for step in v7_steps}) < 2:
                raise ContractError(
                    f"composition {composition_id} must contain at least two "
                    "operation/external tasks"
                )
            compositions.append(Composition(
                composition_id,
                v7_steps,
                dict(_object(row.get("metadata", {}), f"composition {composition_id}.metadata")),
                expression,
            ))
            continue
        if set(row) != {"id", "steps", "metadata"}:
            raise ContractError("composition must contain exactly id, steps, and metadata")
        composition_id = _identifier(row.get("id"), "composition.id")
        legacy_steps: list[CompositionStep] = []
        for step_value in _array(row.get("steps"), f"composition {composition_id}.steps"):
            step = _object(step_value, f"composition {composition_id}.step")
            required_step_fields = (
                {"task", "timing", "count", "outcome_type"}
                if schema in {
                    "dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6",
                }
                else {"task", "timing", "count"}
            )
            if set(step) != required_step_fields:
                suffix = ", and outcome_type" if schema in {
                    "dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6",
                } else ""
                raise ContractError(
                    "composition step must contain exactly task, timing, count" + suffix
                )
            count = _positive(step.get("count"), "composition step count")
            if not count.is_integer():
                raise ContractError("composition step count must be an integer")
            legacy_steps.append(CompositionStep(
                _identifier(step.get("task"), f"composition {composition_id}.step.task"),
                _identifier(step.get("timing"), f"composition {composition_id}.step.timing"),
                int(count),
                _identifier(
                    step.get("outcome_type"),
                    f"composition {composition_id}.step.outcome_type",
                ) if schema in {
                    "dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6",
                } else None,
            ))
        task_refs = tuple(step.task for step in legacy_steps)
        if len(set(task_refs)) < 2:
            raise ContractError(
                f"composition {composition_id} must contain at least two operation/external tasks"
            )
        if len(task_refs) != len(set(task_refs)):
            raise ContractError(
                f"composition {composition_id} must combine repeated executions with step.count"
            )
        compositions.append(Composition(
            composition_id,
            tuple(legacy_steps),
            dict(_object(row.get("metadata", {}), f"composition {composition_id}.metadata")),
        ))

    state_claims: list[StateClaim] = []
    for value in _array(raw.get("state_claims", ()), "state_claims"):
        row = _object(value, "state_claim")
        claim_id = _identifier(row.get("id"), "state_claim.id")
        kind = _identifier(row.get("kind"), f"state_claim {claim_id}.kind")
        if kind == "linear_invariant":
            required = {"id", "kind", "expression", "operator", "bound", "metadata"}
            if set(row) != required:
                raise ContractError(
                    f"state_claim {claim_id} linear_invariant fields mismatch"
                )
            invariant_expression = {
                _identifier(resource_id, f"state_claim {claim_id}.expression resource"): (
                    _finite_number(weight, f"state_claim {claim_id}.expression weight")
                )
                for resource_id, weight in _object(
                    row.get("expression"), f"state_claim {claim_id}.expression",
                ).items()
            }
            if not invariant_expression or any(
                weight == 0 for weight in invariant_expression.values()
            ):
                raise ContractError(
                    f"state_claim {claim_id}.expression must contain nonzero coefficients"
                )
            operator = _identifier(row.get("operator"), f"state_claim {claim_id}.operator")
            if operator not in {"eq", "lte", "gte"}:
                raise ContractError(
                    f"state_claim {claim_id}.operator must be eq, lte, or gte"
                )
            specification: Mapping[str, Any] = {
                "expression": invariant_expression,
                "operator": operator,
                "bound": _finite_number(row.get("bound"), f"state_claim {claim_id}.bound"),
            }
        elif kind == "bounded_non_starvation":
            required = {
                "id", "kind", "inventory_resources", "producer", "consumer",
                "horizon", "metadata",
            }
            if set(row) != required:
                raise ContractError(
                    f"state_claim {claim_id} bounded_non_starvation fields mismatch"
                )
            inventory_resources = tuple(
                _identifier(item, f"state_claim {claim_id}.inventory_resources")
                for item in _array(
                    row.get("inventory_resources"),
                    f"state_claim {claim_id}.inventory_resources",
                )
            )
            if not inventory_resources or len(inventory_resources) != len(
                set(inventory_resources)
            ):
                raise ContractError(
                    f"state_claim {claim_id}.inventory_resources must be nonempty and unique"
                )
            endpoints: dict[str, dict[str, str]] = {}
            for endpoint in ("producer", "consumer"):
                endpoint_row = _object(
                    row.get(endpoint), f"state_claim {claim_id}.{endpoint}",
                )
                if set(endpoint_row) != {"task", "timing"}:
                    raise ContractError(
                        f"state_claim {claim_id}.{endpoint} must contain task and timing"
                    )
                endpoints[endpoint] = {
                    "task": _identifier(
                        endpoint_row.get("task"),
                        f"state_claim {claim_id}.{endpoint}.task",
                    ),
                    "timing": _identifier(
                        endpoint_row.get("timing"),
                        f"state_claim {claim_id}.{endpoint}.timing",
                    ),
                }
            horizon = _positive(row.get("horizon"), f"state_claim {claim_id}.horizon")
            if not horizon.is_integer():
                raise ContractError(f"state_claim {claim_id}.horizon must be an integer")
            specification = {
                "inventory_resources": inventory_resources,
                **endpoints,
                "horizon": int(horizon),
            }
        elif kind == "bounded_response":
            required = {
                "id", "kind", "trigger_resource", "response_task", "response_timing",
                "upper_ms", "metadata",
            }
            if set(row) != required:
                raise ContractError(f"state_claim {claim_id} bounded_response fields mismatch")
            specification = {
                "trigger_resource": _identifier(
                    row.get("trigger_resource"),
                    f"state_claim {claim_id}.trigger_resource",
                ),
                "response_task": _identifier(
                    row.get("response_task"), f"state_claim {claim_id}.response_task",
                ),
                "response_timing": _identifier(
                    row.get("response_timing"),
                    f"state_claim {claim_id}.response_timing",
                ),
                "upper_ms": _positive(
                    row.get("upper_ms"), f"state_claim {claim_id}.upper_ms",
                ),
            }
        else:
            raise ContractError(
                f"state_claim {claim_id}.kind must be linear_invariant, "
                "bounded_non_starvation, or bounded_response"
            )
        state_claims.append(StateClaim(
            claim_id,
            kind,
            specification,
            dict(_object(row.get("metadata", {}), f"state_claim {claim_id}.metadata")),
        ))

    contract = Contract(
        str(schema), tuple(workers), tuple(tasks), tuple(resources),
        dict(_object(raw.get("metadata", {}), "metadata")),
        tuple(compositions),
        tuple(state_claims),
    )
    _validate(contract)
    return contract


def _expression_entries(expression: CompositionExpression) -> tuple[CompositionStep, ...]:
    if expression.kind == "leaf":
        assert expression.step is not None
        return (expression.step,)
    if expression.kind == "sequence":
        return _expression_entries(expression.children[0])
    if expression.kind == "parallel_all":
        return tuple(
            step for child in expression.children for step in _expression_entries(child)
        )
    return _expression_entries(expression.children[0])


def _expression_exits(expression: CompositionExpression) -> tuple[CompositionStep, ...]:
    if expression.kind == "leaf":
        assert expression.step is not None
        return (expression.step,)
    if expression.kind == "sequence":
        return _expression_exits(expression.children[-1])
    if expression.kind == "parallel_all":
        return tuple(
            step for child in expression.children for step in _expression_exits(child)
        )
    return _expression_exits(expression.children[0])


def _require_expression_edges(
    upstream: CompositionExpression,
    downstream: CompositionExpression,
    tasks: Mapping[str, Task],
    composition_id: str,
) -> None:
    for downstream_step in _expression_entries(downstream):
        downstream_task = tasks[downstream_step.task]
        for upstream_step in _expression_exits(upstream):
            if not any(
                dependency.task == upstream_step.task
                and dependency.outcome_type == upstream_step.outcome_type
                for dependency in downstream_task.typed_dependencies
            ):
                raise ContractError(
                    f"composition {composition_id} is not a real typed workflow edge: "
                    f"{upstream_step.task}/{upstream_step.outcome_type} does not feed "
                    f"{downstream_step.task}/{downstream_task.input_type}"
                )


def _validate_composition_expression_edges(
    expression: CompositionExpression,
    tasks: Mapping[str, Task],
    composition_id: str,
) -> None:
    for child in expression.children:
        _validate_composition_expression_edges(child, tasks, composition_id)
    if expression.kind == "sequence":
        for upstream, downstream in zip(
            expression.children, expression.children[1:], strict=False,
        ):
            _require_expression_edges(upstream, downstream, tasks, composition_id)
    if expression.kind == "parallel_all":
        branch_tasks = [
            {step.task for step in composition_steps(child)}
            for child in expression.children
        ]
        for branch_index, task_ids in enumerate(branch_tasks):
            other_task_ids = set().union(*(
                identifiers
                for index, identifiers in enumerate(branch_tasks)
                if index != branch_index
            ))
            hidden_edges = sorted(
                (dependency.task, task_id)
                for task_id in task_ids
                for dependency in tasks[task_id].typed_dependencies
                if dependency.task in other_task_ids
            )
            if hidden_edges:
                edge = hidden_edges[0]
                raise ContractError(
                    f"composition {composition_id} parallel_all branches are not independent: "
                    f"{edge[0]} feeds {edge[1]} across branches"
                )


def _validate(contract: Contract) -> None:
    for label, identifiers in (
        ("worker", [item.id for item in contract.workers]),
        ("task", [item.id for item in contract.tasks]),
        ("resource", [item.id for item in contract.resources]),
        ("composition", [item.id for item in contract.compositions]),
        ("state claim", [item.id for item in contract.state_claims]),
    ):
        if label not in {"resource", "composition", "state claim"} and not identifiers:
            raise ContractError(f"contract must declare at least one {label}")
        if len(identifiers) != len(set(identifiers)):
            raise ContractError(f"{label} IDs must be unique")
    workers = contract.worker_by_id
    tasks = contract.task_by_id
    resources = contract.resource_by_id
    if contract.schema in {"dagcert-contract/v6", "dagcert-contract/v7"}:
        callable_binding_ids = [
            binding.id for task in contract.tasks for binding in task.callable_bindings
        ]
        if len(callable_binding_ids) != len(set(callable_binding_ids)):
            raise ContractError("callable binding IDs must be unique across the contract")
        for task in contract.tasks:
            if task.callable_bindings and task.role != "operation":
                raise ContractError(
                    f"task {task.id} callable bindings require role operation"
                )
            fields = [binding.field for binding in task.callable_bindings]
            if len(fields) != len(set(fields)):
                raise ContractError(
                    f"task {task.id} callable bindings must target unique input fields"
                )
        external_paths = {
            task.implementation.path
            for task in contract.tasks
            if task.role == "external" and task.implementation is not None
        }
        proved_paths = {
            task.implementation.path
            for task in contract.tasks
            if task.role == "operation" and task.implementation is not None
        }
        shared_paths = external_paths & proved_paths
        if shared_paths:
            raise ContractError(
                "external adapters must be in separate modules from proved operations so Nagini "
                f"can overlay only the declared ContractOnly boundary: {sorted(shared_paths)}"
            )
        implementation_paths = {
            task.implementation.path
            for task in contract.tasks if task.implementation is not None
        }
        for task in contract.tasks:
            if (
                task.external_contract is not None
                and task.external_contract.stub_path in implementation_paths
            ):
                raise ContractError(
                    f"external task {task.id} ContractOnly stub must be separate from every real "
                    "implementation module"
                )
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
        if contract.schema in {
            "dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6",
            "dagcert-contract/v7",
        }:
            for dependency in task.typed_dependencies:
                upstream = tasks.get(dependency.task)
                if upstream is None:
                    continue
                if dependency.outcome_type not in upstream.outcome_by_type:
                    raise ContractError(
                        f"task {task.id} dependency cites {dependency.task} outcome "
                        f"{dependency.outcome_type!r}, which is not in the upstream source union"
                    )
                if dependency.input_field is None and dependency.outcome_type != task.input_type:
                    raise ContractError(
                        f"task {task.id} source input {task.input_type!r} does not accept typed edge "
                        f"{dependency.task}/{dependency.outcome_type}"
                    )
                if dependency.input_field is not None:
                    if contract.schema != "dagcert-contract/v7":
                        raise ContractError(
                            f"task {task.id} dependency input_field requires v7"
                        )
                    assert task.source_signature is not None
                    field_types = dict(task.source_signature.input_fields)
                    actual_type = field_types.get(dependency.input_field)
                    if actual_type is None:
                        raise ContractError(
                            f"task {task.id} dependency targets unknown source input field "
                            f"{dependency.input_field!r}"
                        )
                    if actual_type != dependency.outcome_type:
                        raise ContractError(
                            f"task {task.id} source input field {dependency.input_field!r} "
                            f"expects {actual_type!r}, not {dependency.outcome_type!r} from "
                            f"{dependency.task}"
                        )
            if contract.schema in {
                "dagcert-contract/v5", "dagcert-contract/v6", "dagcert-contract/v7",
            } and task.error_budget is not None:
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
            if task.role == "external":
                external = task.external_contract
                if external is None:
                    raise ContractError(f"external task {task.id} lacks an external contract")
                if task.error_budget is None:
                    raise ContractError(
                        f"external task {task.id} requires an engineering error budget; use "
                        "bad_event_probability_upper 0 for a p=1 premise"
                    )
                if task.error_budget.bad_event_probability_upper != 0:
                    raise ContractError(
                        f"external task {task.id} ContractOnly proof is a p=1 premise and therefore "
                        "requires bad_event_probability_upper 0; model nonzero provider failure "
                        "inside executable typed operations instead"
                    )
                if task.error_budget.good_outcomes != (external.success_outcome,):
                    raise ContractError(
                        f"external task {task.id} error budget must classify exactly its success "
                        f"outcome {external.success_outcome!r} as good"
                    )
                if task.error_budget.evidence_case != external.evidence_case:
                    raise ContractError(
                        f"external task {task.id} error-budget evidence case must equal external "
                        f"contract case {external.evidence_case!r}"
                    )
                if external.evidence_case not in task.timings:
                    raise ContractError(
                        f"external task {task.id} cites unknown conformance evidence case "
                        f"{external.evidence_case!r}"
                    )
        for resource_id, effect in (*task.resources.items(), *task.start_resources.items()):
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
            if tasks[task_id].role not in {"operation", "external"}
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
            if contract.schema in {
                "dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6",
                "dagcert-contract/v7",
            }:
                if step.outcome_type not in task.outcome_by_type:
                    raise ContractError(
                        f"composition {composition.id} step {step.task} cites outcome "
                        f"{step.outcome_type!r} outside the task's source union"
                    )
                if (
                    contract.schema != "dagcert-contract/v7"
                    and step.count > 1
                    and step.outcome_type != task.input_type
                ):
                    raise ContractError(
                        f"composition {composition.id} repeats {step.task}, but outcome "
                        f"{step.outcome_type!r} is not the task input {task.input_type!r}"
                    )
        if contract.schema in {"dagcert-contract/v4", "dagcert-contract/v5", "dagcert-contract/v6"}:
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
        if contract.schema == "dagcert-contract/v7":
            assert composition.expression is not None
            _validate_composition_expression_edges(
                composition.expression, tasks, composition.id,
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
    for claim in contract.state_claims:
        spec = claim.specification
        if claim.kind == "linear_invariant":
            unknown_resources = set(spec["expression"]) - set(resources)
            if unknown_resources:
                raise ContractError(
                    f"state_claim {claim.id} cites unknown resources "
                    f"{sorted(unknown_resources)}"
                )
        elif claim.kind == "bounded_non_starvation":
            unknown_resources = set(spec["inventory_resources"]) - set(resources)
            if unknown_resources:
                raise ContractError(
                    f"state_claim {claim.id} cites unknown inventory resources "
                    f"{sorted(unknown_resources)}"
                )
            for endpoint in ("producer", "consumer"):
                endpoint_spec = spec[endpoint]
                state_task = tasks.get(endpoint_spec["task"])
                if state_task is None:
                    raise ContractError(
                        f"state_claim {claim.id} cites unknown {endpoint} task "
                        f"{endpoint_spec['task']!r}"
                    )
                timing = state_task.timings.get(endpoint_spec["timing"])
                if timing is None:
                    raise ContractError(
                        f"state_claim {claim.id} cites unknown {endpoint} timing "
                        f"{endpoint_spec['task']}/{endpoint_spec['timing']}"
                    )
                if timing.metric != "duration":
                    raise ContractError(
                        f"state_claim {claim.id} {endpoint} timing must be a duration metric"
                    )
                required_bound = "upper_ms" if endpoint == "producer" else "lower_ms"
                if getattr(timing, required_bound) is None:
                    raise ContractError(
                        f"state_claim {claim.id} {endpoint} timing requires {required_bound}"
                    )
        elif claim.kind == "bounded_response":
            trigger = spec["trigger_resource"]
            if trigger not in resources:
                raise ContractError(
                    f"state_claim {claim.id} cites unknown trigger resource {trigger!r}"
                )
            response_task = tasks.get(spec["response_task"])
            if response_task is None or spec["response_timing"] not in response_task.timings:
                raise ContractError(
                    f"state_claim {claim.id} cites unknown response timing "
                    f"{spec['response_task']}/{spec['response_timing']}"
                )
            timing = response_task.timings[spec["response_timing"]]
            if timing.metric != "wait" or timing.upper_ms is None:
                raise ContractError(
                    f"state_claim {claim.id} response timing must be a bounded wait metric"
                )
            effect = response_task.start_resources.get(trigger, ResourceEffect())
            if effect.consume <= 0:
                raise ContractError(
                    f"state_claim {claim.id} response task must consume trigger resource "
                    f"{trigger!r} at start"
                )
    contract.topological_tasks()
