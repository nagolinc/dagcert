"""Restricted lifecycle and finite-horizon flow proofs for Dagcert v7."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil
from typing import Mapping

from .analysis import AnalysisReport, TimingResult
from .contract import Contract, ResourceEffect, StateClaim, Task


@dataclass(frozen=True, slots=True)
class StateProof:
    claim_id: str
    passed: bool
    summary: str
    trace: tuple[str, ...] = ()


def prove_state_claim(
    claim: StateClaim, contract: Contract, analysis: AnalysisReport,
) -> StateProof:
    if claim.kind == "linear_invariant":
        return _prove_linear_invariant(claim, contract)
    if claim.kind == "bounded_non_starvation":
        return _prove_bounded_non_starvation(claim, contract, analysis)
    if claim.kind == "bounded_response":
        return _prove_bounded_response(claim, contract, analysis)
    return StateProof(claim.id, False, f"unsupported state claim kind {claim.kind!r}")


def _weighted_delta(
    effects: Mapping[str, ResourceEffect], coefficients: Mapping[str, float],
) -> Fraction:
    return sum(
        (
            Fraction(str(coefficients.get(resource_id, 0.0)))
            * Fraction(str(effect.produce - effect.consume))
            for resource_id, effect in effects.items()
        ),
        start=Fraction(0),
    )


def _transitions(contract: Contract) -> tuple[tuple[str, Mapping[str, ResourceEffect]], ...]:
    rows: list[tuple[str, Mapping[str, ResourceEffect]]] = []
    for task in contract.tasks:
        rows.append((f"start:{task.id}", task.start_resources))
        rows.extend(
            (f"finish:{task.id}/{outcome.type}", outcome.resources)
            for outcome in task.outcomes
        )
    return tuple(rows)


def _prove_linear_invariant(claim: StateClaim, contract: Contract) -> StateProof:
    spec = claim.specification
    coefficients = spec["expression"]
    operator = spec["operator"]
    bound = Fraction(str(spec["bound"]))
    initial = sum(
        (
            Fraction(str(weight))
            * Fraction(str(contract.resource_by_id[resource_id].initial))
            for resource_id, weight in coefficients.items()
        ),
        start=Fraction(0),
    )
    initial_passed = {
        "eq": initial == bound,
        "lte": initial <= bound,
        "gte": initial >= bound,
    }[operator]
    if not initial_passed:
        return StateProof(
            claim.id,
            False,
            "initial state violates the declared affine invariant",
            (f"initial expression={float(initial):g}; required {operator} {float(bound):g}",),
        )
    for label, effects in _transitions(contract):
        delta = _weighted_delta(effects, coefficients)
        preserved = {
            "eq": delta == 0,
            "lte": delta <= 0,
            "gte": delta >= 0,
        }[operator]
        if not preserved:
            return StateProof(
                claim.id,
                False,
                "a declared lifecycle transition does not preserve the affine invariant",
                (
                    f"initial expression={float(initial):g}",
                    f"transition={label}",
                    f"expression delta={float(delta):+g}",
                    f"required preservation for {operator} {float(bound):g}",
                ),
            )
    return StateProof(
        claim.id,
        True,
        f"initial value {float(initial):g} and every start/outcome transition preserve "
        f"expression {operator} {float(bound):g}",
    )


def _inventory_delta(
    effects: Mapping[str, ResourceEffect], inventory: set[str],
) -> float:
    return sum(
        effect.produce - effect.consume
        for resource_id, effect in effects.items()
        if resource_id in inventory
    )


def _invocation_inventory_deltas(task: Task, inventory: set[str]) -> tuple[float, ...]:
    start = _inventory_delta(task.start_resources, inventory)
    return tuple(
        start + _inventory_delta(outcome.resources, inventory)
        for outcome in task.outcomes
    )


def _timing_result(
    analysis: AnalysisReport, task_id: str, timing: str,
) -> TimingResult | None:
    return next(
        (
            result for result in analysis.timings
            if result.task_id == task_id and result.case == timing and result.passed
        ),
        None,
    )


def _prove_bounded_non_starvation(
    claim: StateClaim, contract: Contract, analysis: AnalysisReport,
) -> StateProof:
    spec = claim.specification
    inventory = set(spec["inventory_resources"])
    producer = contract.task_by_id[spec["producer"]["task"]]
    consumer = contract.task_by_id[spec["consumer"]["task"]]
    producer_deltas = _invocation_inventory_deltas(producer, inventory)
    consumer_deltas = _invocation_inventory_deltas(consumer, inventory)
    guaranteed_production = min(producer_deltas)
    maximum_depletion = max(-delta for delta in consumer_deltas)
    if guaranteed_production <= 0:
        outcome = producer.outcomes[producer_deltas.index(guaranteed_production)].type
        return StateProof(
            claim.id,
            False,
            "the producer does not replenish inventory on every typed outcome",
            (
                f"producer={producer.id}",
                f"outcome={outcome}",
                f"inventory delta={guaranteed_production:+g}",
            ),
        )
    if maximum_depletion <= 0:
        return StateProof(
            claim.id,
            True,
            "the consumer cannot deplete the declared inventory on any typed outcome",
        )
    producer_timing = _timing_result(
        analysis, producer.id, spec["producer"]["timing"],
    )
    consumer_timing = _timing_result(
        analysis, consumer.id, spec["consumer"]["timing"],
    )
    if producer_timing is None or producer_timing.certified_upper_ms is None:
        return StateProof(
            claim.id, False, "producer lacks a passing certified maximum completion bound",
        )
    if consumer_timing is None or consumer_timing.certified_lower_ms is None:
        return StateProof(
            claim.id, False, "consumer lacks a passing certified minimum service bound",
        )
    initial = sum(contract.resource_by_id[item].initial for item in inventory)
    if initial <= 0:
        return StateProof(
            claim.id,
            False,
            "the declared inventory is empty initially",
            ("time=0ms", "inventory=0"),
        )
    producer_period = Fraction(str(producer_timing.certified_upper_ms))
    consumer_period = Fraction(str(consumer_timing.certified_lower_ms))
    producer_parallelism = contract.worker_by_id[producer.worker].concurrency
    consumer_parallelism = contract.worker_by_id[consumer.worker].concurrency
    horizon = int(spec["horizon"])
    for completed in range(1, horizon):
        consumer_batches = ceil(completed / consumer_parallelism)
        elapsed = consumer_period * consumer_batches
        # A completion exactly tied with the consumer completion cannot be counted without an
        # event-ordering proof. Count only producer batches that completed strictly earlier.
        producer_batches = max(0, ceil(elapsed / producer_period) - 1)
        produced = (
            producer_batches * producer_parallelism * guaranteed_production
        )
        remaining = initial + produced - completed * maximum_depletion
        if remaining <= 0:
            return StateProof(
                claim.id,
                False,
                "the finite-horizon worst-case supply envelope reaches zero",
                (
                    f"consumer completions={completed}/{horizon}",
                    f"elapsed_ms={float(elapsed):g}",
                    f"initial_inventory={initial:g}",
                    f"guaranteed_produced={produced:g}",
                    f"maximum_consumed={completed * maximum_depletion:g}",
                    f"remaining_inventory={remaining:g}",
                ),
            )
    return StateProof(
        claim.id,
        True,
        f"inventory remains positive before every one of {horizon} bounded consumer "
        "completions under the declared producer/consumer timing envelopes",
    )


def _prove_bounded_response(
    claim: StateClaim, contract: Contract, analysis: AnalysisReport,
) -> StateProof:
    spec = claim.specification
    task_id = spec["response_task"]
    timing_name = spec["response_timing"]
    result = _timing_result(analysis, task_id, timing_name)
    if result is None or result.certified_upper_ms is None:
        return StateProof(
            claim.id,
            False,
            "response path lacks a passing certified wait bound",
            (f"timing:{task_id}/{timing_name}",),
        )
    limit = float(spec["upper_ms"])
    if result.certified_upper_ms > limit:
        return StateProof(
            claim.id,
            False,
            "certified response wait exceeds the declared response bound",
            (
                f"timing:{task_id}/{timing_name}={result.certified_upper_ms:g}ms",
                f"required<={limit:g}ms",
            ),
        )
    return StateProof(
        claim.id,
        True,
        f"trigger inventory is consumed by {task_id} with certified wait "
        f"{result.certified_upper_ms:g}ms <= {limit:g}ms",
    )
