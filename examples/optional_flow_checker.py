"""Optional derived guarantees using only the four Dagcert primitives.

This example deliberately adds no ComfyUI, queue, blocked-state, or model-lag
primitive. It derives those statements from task resource flow, worker capacity,
and measured or assumed timing bounds.
"""

from __future__ import annotations

from dataclasses import dataclass

from dagcert import CheckContext, CheckFinding, CheckResult, analyze_contract


@dataclass(frozen=True, slots=True)
class SupplyClaim:
    consumer_task: str
    consumer_duration_case: str
    producer_task: str
    producer_interval_case: str
    work_resource: str


@dataclass(frozen=True, slots=True)
class LagClaim:
    producer_task: str
    producer_interval_case: str
    updater_task: str
    updater_duration_case: str
    lag_resource: str
    maximum_lag: float


def check_flow_guarantees(
    context: CheckContext,
    *,
    supply: SupplyClaim,
    lag: LagClaim,
) -> CheckResult:
    report = analyze_contract(
        context.contract,
        context.timings,
        source_fingerprint=context.source_fingerprint,
    )
    findings: list[CheckFinding] = []
    claims: list[str] = []
    facts: dict[str, object] = {
        "conditional": report.conditional,
        "assumptions": list(report.assumptions),
        "claims": claims,
    }

    timing_results = {
        (item.task_id, item.case): item
        for item in report.timings
        if item.passed
    }
    tasks = context.contract.task_by_id
    resources = context.contract.resource_by_id

    producer = tasks[supply.producer_task]
    consumer = tasks[supply.consumer_task]
    work = resources[supply.work_resource]
    produced = producer.resources[supply.work_resource].produce
    consumed = consumer.resources[supply.work_resource].consume
    arrival = timing_results[(producer.id, supply.producer_interval_case)]
    service = timing_results[(consumer.id, supply.consumer_duration_case)]
    if arrival.certified_upper_ms is None or service.certified_lower_ms is None:
        findings.append(CheckFinding(
            "insufficient-supply-bounds",
            consumer.id,
            "non-starvation requires an upper arrival interval and lower service duration",
        ))
    else:
        minimum_supply_per_second = produced * 1000 / arrival.certified_upper_ms
        maximum_consumption_per_second = (
            consumed
            * context.contract.worker_by_id[consumer.worker].concurrency
            * 1000
            / service.certified_lower_ms
        )
        warm_start_required = consumed * context.contract.worker_by_id[consumer.worker].concurrency
        supply_passed = (
            minimum_supply_per_second >= maximum_consumption_per_second
            and work.initial >= warm_start_required
        )
        if not supply_passed:
            findings.append(CheckFinding(
                "task-may-starve",
                consumer.id,
                f"minimum supply {minimum_supply_per_second:.3f}/s, maximum consumption "
                f"{maximum_consumption_per_second:.3f}/s, initial work {work.initial:g}, "
                f"warm start requires {warm_start_required:g}",
            ))
        facts["supply"] = {
            "task": consumer.id,
            "minimum_supply_per_second": minimum_supply_per_second,
            "maximum_consumption_per_second": maximum_consumption_per_second,
            "initial_work": work.initial,
            "warm_start_required": warm_start_required,
            "passed": supply_passed,
        }
        if supply_passed:
            claims.append(f"task:{consumer.id} is not starved after warm-up")

    lag_producer = tasks[lag.producer_task]
    updater = tasks[lag.updater_task]
    lag_resource = resources[lag.lag_resource]
    generation_interval = timing_results[(lag_producer.id, lag.producer_interval_case)]
    update_duration = timing_results[(updater.id, lag.updater_duration_case)]
    if generation_interval.certified_lower_ms is None or update_duration.certified_upper_ms is None:
        findings.append(CheckFinding(
            "insufficient-lag-bounds",
            updater.id,
            "generation lag requires a lower generation interval and upper update duration",
        ))
    else:
        maximum_generation_rate = (
            lag_producer.resources[lag.lag_resource].produce
            * 1000
            / generation_interval.certified_lower_ms
        )
        minimum_update_rate = (
            updater.resources[lag.lag_resource].consume
            * context.contract.worker_by_id[updater.worker].concurrency
            * 1000
            / update_duration.certified_upper_ms
        )
        lag_passed = (
            lag_resource.initial <= lag.maximum_lag
            and lag_resource.capacity <= lag.maximum_lag
            and minimum_update_rate >= maximum_generation_rate
        )
        if not lag_passed:
            findings.append(CheckFinding(
                "generation-lag-not-bounded",
                updater.id,
                f"maximum generation rate {maximum_generation_rate:.3f}/s, minimum update rate "
                f"{minimum_update_rate:.3f}/s, initial/capacity "
                f"{lag_resource.initial:g}/{lag_resource.capacity:g}, requested {lag.maximum_lag:g}",
            ))
        facts["lag"] = {
            "task": updater.id,
            "maximum_generation_rate": maximum_generation_rate,
            "minimum_update_rate": minimum_update_rate,
            "maximum_generations": lag.maximum_lag,
            "passed": lag_passed,
        }
        if lag_passed:
            claims.append(
                f"task:{updater.id} remains at most {lag.maximum_lag:g} generations out of date"
            )

    if report.structural_progress.passed:
        claims.append("the declared DAG has no structurally blocked task")
    else:
        findings.append(CheckFinding(
            "structural-progress-failed",
            "contract",
            "core structural progress analysis did not pass",
        ))

    primitive_refs = {
        f"task:{supply.producer_task}",
        f"task:{supply.consumer_task}",
        f"resource:{supply.work_resource}",
        f"timing:{supply.producer_task}/{supply.producer_interval_case}",
        f"timing:{supply.consumer_task}/{supply.consumer_duration_case}",
        f"task:{lag.producer_task}",
        f"task:{lag.updater_task}",
        f"resource:{lag.lag_resource}",
        f"timing:{lag.producer_task}/{lag.producer_interval_case}",
        f"timing:{lag.updater_task}/{lag.updater_duration_case}",
    }
    return CheckResult(
        checker="example.flow-guarantees/v1",
        passed=not findings,
        source_fingerprint=context.source_fingerprint,
        contract_sha256=context.contract_sha256,
        evidence_sha256=context.evidence_sha256,
        requirements_sha256=context.requirements_sha256,
        primitive_refs=tuple(sorted(primitive_refs)),
        findings=tuple(findings),
        facts=facts,
    )
