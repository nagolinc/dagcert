"""Deterministic checks and derived guarantees over the four primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any, Iterable

from .contract import Contract, Task, Timing
from .evidence import TimingSample


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    subject: str
    message: str


@dataclass(frozen=True, slots=True)
class TimingResult:
    task_id: str
    case: str
    metric: str
    evidence: str
    samples: int
    observed_min_ms: float | None
    observed_upper_ms: float | None
    certified_lower_ms: float | None
    certified_upper_ms: float | None
    required_lower_ms: float | None
    required_upper_ms: float | None
    passed: bool


@dataclass(frozen=True, slots=True)
class StructuralProgress:
    passed: bool
    claim: str
    task_order: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    passed: bool
    conditional: bool
    assumptions: tuple[str, ...]
    structural_progress: StructuralProgress
    timings: tuple[TimingResult, ...]
    findings: tuple[Finding, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "conditional": self.conditional,
            "assumptions": list(self.assumptions),
            "structural_progress": {
                **asdict(self.structural_progress),
                "task_order": list(self.structural_progress.task_order),
                "assumptions": list(self.structural_progress.assumptions),
            },
            "timings": [asdict(item) for item in self.timings],
            "findings": [asdict(item) for item in self.findings],
        }


def analyze_contract(
    contract: Contract, samples: Iterable[TimingSample], *, source_fingerprint: str,
) -> AnalysisReport:
    evidence = tuple(samples)
    findings: list[Finding] = []
    timing_results: list[TimingResult] = []
    assumptions: list[str] = []
    tasks = contract.task_by_id

    for sample in evidence:
        task = tasks.get(sample.task_id)
        if task is None:
            findings.append(Finding("unknown-task-evidence", sample.task_id, "timing names no declared task"))
            continue
        if sample.case not in task.timings:
            findings.append(Finding("unknown-timing-case", f"{sample.task_id}/{sample.case}", "timing names no declared case"))
        if sample.worker_id != task.worker:
            findings.append(Finding("wrong-worker", sample.task_id, f"expected {task.worker}, observed {sample.worker_id}"))
        if sample.source_fingerprint != source_fingerprint:
            findings.append(Finding("wrong-source", sample.task_id, "timing was observed against another source fingerprint"))
        worker = contract.worker_by_id[task.worker]
        if sample.observed_worker_concurrency is not None and sample.observed_worker_concurrency > worker.concurrency:
            findings.append(Finding(
                "worker-concurrency-exceeded", worker.id,
                f"declared {worker.concurrency}, observed {sample.observed_worker_concurrency}",
            ))
        timing = task.timings.get(sample.case)
        if timing is not None and timing.metric == "duration" and sample.succeeded:
            _check_execution_observation(task, sample, contract, findings)

    for task in contract.tasks:
        for case, requirement in task.timings.items():
            subject = f"{task.id}/{case}"
            if requirement.evidence == "assumed":
                description = _assumption(task.id, case, requirement)
                assumptions.append(description)
                timing_results.append(_assumed_result(task.id, case, requirement))
                continue
            usable = [
                sample for sample in evidence
                if sample.task_id == task.id and sample.case == case and sample.succeeded
                and sample.worker_id == task.worker and sample.source_fingerprint == source_fingerprint
            ]
            if len(usable) < requirement.minimum_samples:
                findings.append(Finding(
                    "insufficient-timing-evidence", subject,
                    f"requires {requirement.minimum_samples} successful samples, observed {len(usable)}",
                ))
                timing_results.append(_failed_result(task.id, case, requirement, len(usable)))
                continue
            values = [sample.value_ms for sample in usable]
            observed_min = min(values)
            observed_upper = _select_upper(values, requirement)
            certified_lower = round(observed_min / requirement.safety_factor, 12)
            certified_upper = round(observed_upper * requirement.safety_factor, 12)
            lower_passed = requirement.lower_ms is None or certified_lower > requirement.lower_ms
            upper_passed = requirement.upper_ms is None or certified_upper < requirement.upper_ms
            passed = lower_passed and upper_passed
            if not lower_passed:
                findings.append(Finding(
                    "timing-lower-bound-missed", subject,
                    f"observed minimum {observed_min:.3f}ms / {requirement.safety_factor:.3f} "
                    f"= {certified_lower:.3f}ms, must be > {requirement.lower_ms:.3f}ms",
                ))
            if not upper_passed:
                findings.append(Finding(
                    "timing-upper-bound-missed", subject,
                    f"observed upper {observed_upper:.3f}ms x {requirement.safety_factor:.3f} "
                    f"= {certified_upper:.3f}ms, must be < {requirement.upper_ms:.3f}ms",
                ))
            timing_results.append(TimingResult(
                task.id, case, requirement.metric, requirement.evidence, len(usable),
                observed_min, observed_upper, certified_lower, certified_upper,
                requirement.lower_ms, requirement.upper_ms, passed,
            ))

    blocked = _structurally_blocked_tasks(contract)
    for task_id, reason in blocked.items():
        findings.append(Finding("structurally-blocked-task", task_id, reason))

    passed = not findings
    progress_assumptions = (
        "declared resource effects match runtime acquisition and flow",
        "reachable producer task types may recur until a resource reaches usable capacity",
        "resource acquisition is atomic and scheduling is fair",
        *assumptions,
    )
    progress = StructuralProgress(
        passed=passed,
        claim="every declared task has a feasible worker/resource path and finite completion evidence",
        task_order=contract.topological_tasks(),
        assumptions=progress_assumptions,
    )
    return AnalysisReport(
        passed, bool(assumptions), tuple(assumptions), progress,
        tuple(timing_results), tuple(findings),
    )


def _select_upper(values: list[float], requirement: Timing) -> float:
    ordered = sorted(values)
    if requirement.policy == "max":
        return ordered[-1]
    assert requirement.percentile is not None
    rank = max(1, ceil(requirement.percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def _assumption(task_id: str, case: str, timing: Timing) -> str:
    parts = []
    if timing.lower_ms is not None:
        parts.append(f"> {timing.lower_ms:g}ms")
    if timing.upper_ms is not None:
        parts.append(f"< {timing.upper_ms:g}ms")
    return f"timing:{task_id}/{case} ({timing.metric}) is assumed {' and '.join(parts)}"


def _assumed_result(task_id: str, case: str, timing: Timing) -> TimingResult:
    return TimingResult(
        task_id, case, timing.metric, timing.evidence, 0, None, None,
        timing.lower_ms, timing.upper_ms, timing.lower_ms, timing.upper_ms, True,
    )


def _failed_result(task_id: str, case: str, timing: Timing, samples: int) -> TimingResult:
    return TimingResult(
        task_id, case, timing.metric, timing.evidence, samples, None, None, None, None,
        timing.lower_ms, timing.upper_ms, False,
    )


def _check_execution_observation(
    task: Task, sample: TimingSample, contract: Contract, findings: list[Finding],
) -> None:
    if sample.observed_input_type != task.input_type:
        findings.append(Finding(
            "wrong-input-type", task.id,
            f"expected {task.input_type}, observed {sample.observed_input_type or 'missing'}",
        ))
    if sample.observed_output_type != task.output_type:
        findings.append(Finding(
            "wrong-output-type", task.id,
            f"expected {task.output_type}, observed {sample.observed_output_type or 'missing'}",
        ))
    observed_by_kind = {
        "acquire": sample.resource_acquired,
        "consume": sample.resource_consumed,
        "produce": sample.resource_produced,
    }
    for resource_id, effect in task.resources.items():
        for kind, observed in observed_by_kind.items():
            declared = getattr(effect, kind)
            actual = observed.get(resource_id)
            if declared > 0 and actual is None:
                findings.append(Finding(
                    "missing-resource-effect-observation", f"{task.id}/{resource_id}",
                    f"missing observed {kind} amount",
                ))
            elif actual is not None:
                invalid = actual > declared if kind == "acquire" else actual != declared
                if invalid:
                    findings.append(Finding(
                        "resource-effect-mismatch", f"{task.id}/{resource_id}",
                        f"declared {kind} {declared:g}, observed {actual:g}",
                    ))
    declared_resources = set(task.resources)
    for kind, observed in observed_by_kind.items():
        for resource_id, actual in observed.items():
            if resource_id not in declared_resources or getattr(task.resources[resource_id], kind) == 0:
                findings.append(Finding(
                    "undeclared-resource-effect", f"{task.id}/{resource_id}",
                    f"observed {kind} {actual:g}",
                ))
    for resource_id, level in sample.resource_levels.items():
        resource = contract.resource_by_id.get(resource_id)
        if resource is None:
            findings.append(Finding("unknown-resource-level", task.id, resource_id))
        elif level > resource.capacity:
            findings.append(Finding(
                "resource-capacity-exceeded", resource_id,
                f"capacity {resource.capacity:g}, observed level {level:g}",
            ))


def _structurally_blocked_tasks(contract: Contract) -> dict[str, str]:
    """Find task types with no dependency/resource path to a first execution.

    Tasks are repeatable types. Once a producer task is reachable, it may recur and
    fill any resource it produces up to that resource's declared capacity. This is
    intentionally a structural reachability check, not a throughput or scheduling
    proof; those use timings and optional checkers.
    """
    reachable: set[str] = set()
    producible: set[str] = set()
    remaining = {task.id: task for task in contract.tasks}
    changed = True
    while changed:
        changed = False
        for task_id, task in tuple(remaining.items()):
            if not set(task.depends_on).issubset(reachable):
                continue
            unavailable = [
                resource_id
                for resource_id, effect in task.resources.items()
                if effect.consume > contract.resource_by_id[resource_id].initial
                and resource_id not in producible
            ]
            if unavailable:
                continue
            reachable.add(task_id)
            producible.update(
                resource_id
                for resource_id, effect in task.resources.items()
                if effect.produce > 0
            )
            remaining.pop(task_id)
            changed = True

    blocked: dict[str, str] = {}
    for task_id, task in remaining.items():
        missing_dependencies = sorted(set(task.depends_on) - reachable)
        unavailable_resources = sorted(
            resource_id
            for resource_id, effect in task.resources.items()
            if effect.consume > contract.resource_by_id[resource_id].initial
            and resource_id not in producible
        )
        reasons: list[str] = []
        if missing_dependencies:
            reasons.append(f"unreachable dependencies {missing_dependencies}")
        if unavailable_resources:
            reasons.append(f"no initial supply or reachable producer for {unavailable_resources}")
        blocked[task_id] = "; ".join(reasons) or "no feasible first-execution path"
    return blocked
