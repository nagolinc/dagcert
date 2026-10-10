"""Behavioral checks of source-bound arrival, service, and inventory derivations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
from typing import Any

import pytest

from dagcert import analyze_contract, load_contract
from dagcert.contract import (
    Composition, CompositionStep, Contract, ContractError, Implementation, Resource, ResourceEffect, StateClaim,
    Task, TaskOutcome, Timing, TypedDependency, Worker,
)
from dagcert.formula import FormulaError, evaluate_formula, validate_claim_formula
from dagcert.requirements import EnglishClaim, EnglishRequirements, audit_translation
from dagcert.temporal import (
    TemporalError, TemporalModel, parse_temporal_spec, prove_temporal_bound,
    temporal_failure_upper, temporal_references, validate_temporal_spec,
)


def _curve(points: list[list[int | float | str]], tail: int | float | str = 0) -> dict[str, Any]:
    return {"points": points, "tail_slope": tail}


def _task(name: str, *, produce: float = 0, consume: float = 0, cost: float = 1) -> Task:
    effect = ResourceEffect(produce=produce, consume=consume)
    return Task(
        name, f"worker-{name}", "Request", "Completed",
        timings={
            "duration": Timing("duration", upper_ms=cost / 2, evidence="assumed", minimum_samples=0),
            "dispatch": Timing("wait", upper_ms=cost / 2, evidence="assumed", minimum_samples=0),
        },
        implementation=Implementation("python", "production.py", name),
        outcomes=(TaskOutcome("Completed", {"bucket": effect}),),
    )


def _contract(tasks: tuple[Task, ...], *, initial: float = 36, capacity: float = 100) -> Contract:
    return Contract(
        "dagcert-contract/v7", tuple(Worker(task.worker, 1) for task in tasks), tasks,
        (Resource("bucket", capacity, initial),),
    )


def _envelopes(task: str, *, rate: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "id": f"arrivals-{task}", "kind": "arrival", "task": task,
            "assumption": "Admitted requests obey the stated arrival envelopes.",
            "horizon_ms": None, "failure_probability_upper": 0, "window": "interval",
            "lower": _curve([[0, 0], [1 / rate, 0]], rate),
            "upper": _curve([[0, 1]], rate),
        },
        {
            "id": f"service-{task}", "kind": "service", "task": task,
            "assumption": "The assigned lane receives this worker time in every backlogged interval.",
            "horizon_ms": None, "failure_probability_upper": 0,
            "slots": 1, "availability": _curve([[0, 0]], 1),
            "duration_timing": "duration", "dispatch_timing": "dispatch",
        },
    ]


def _row(tasks: tuple[Task, ...], *, expression: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "reserve", "kind": "curve_bound",
        "envelopes": [envelope for task in tasks for envelope in _envelopes(task.id)],
        "flows": [
            {"task": task.id, "input": {"arrival": f"arrivals-{task.id}"}, "service": f"service-{task.id}"}
            for task in tasks
        ],
        "expression": expression or {"inventory_lower": "bucket"},
        "operator": "gte", "bound": 30, "start_ms": 0, "end_ms": None, "metadata": {},
    }


def _bucket() -> tuple[Contract, dict[str, Any]]:
    tasks = (_task("pipe_a", produce=1), _task("pipe_b", produce=1), _task("drain", consume=1, cost=0.5))
    contract, row = _contract(tasks), _row(tasks)
    row["envelopes"][-2:] = _envelopes("drain", rate=2)
    return contract, row


def _one_flow() -> tuple[Contract, dict[str, Any]]:
    task = _task("source")
    row = _row((task,), expression={"departures_lower": task.id})
    row["bound"] = 0
    return _contract((task,)), row


def test_two_independent_pipes_keep_bucket_over_thirty_percent_for_all_time() -> None:
    contract, row = _bucket()
    spec = parse_temporal_spec(row)
    validate_temporal_spec(spec, contract)
    lower = TemporalModel(spec, contract).expression({"inventory_lower": "bucket"})
    upper = TemporalModel(spec, contract).expression({"inventory_upper": "bucket"})
    assert lower.infimum() == 31
    assert upper.supremum() == 40
    assert prove_temporal_bound(spec, contract)[0]
    row["bound"] = 32
    assert not prove_temporal_bound(parse_temporal_spec(row), contract)[0]


def test_processing_capacity_without_arrivals_does_not_manufacture_output() -> None:
    contract, row = _one_flow()
    row["envelopes"][0]["lower"] = _curve([[0, 0]])
    row["envelopes"][0]["upper"] = _curve([[0, 0]])
    model = TemporalModel(parse_temporal_spec(row), contract)
    model.validate()
    assert model.expression({"service_lower": "source"}).value(100) == 99
    assert model.expression({"departures_lower": "source"}).value(100) == 0
    assert model.expression({"departures_upper": "source"}).value(100) == 0


def test_nonproducing_typed_outcome_destroys_unconditional_inventory_supply() -> None:
    contract, row = _bucket()
    first = contract.tasks[0]
    contract = replace(contract, tasks=(replace(first, outcomes=first.outcomes + (TaskOutcome("Failed"),)),) + contract.tasks[1:])
    passed, reason = prove_temporal_bound(parse_temporal_spec(row), contract)
    assert not passed
    assert "unbounded below" in reason


def test_shared_worker_capacity_cannot_be_allocated_twice() -> None:
    contract, row = _bucket()
    contract = replace(contract, workers=(Worker("shared", 2),), tasks=tuple(replace(task, worker="shared") for task in contract.tasks))
    with pytest.raises(TemporalError, match="shared worker shared is overallocated"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_shared_resource_capacity_cannot_be_allocated_twice() -> None:
    contract, row = _bucket()
    contract = replace(
        contract, resources=contract.resources + (Resource("gpu", 1),),
        tasks=tuple(replace(task, start_resources={"gpu": ResourceEffect(acquire=1)}) for task in contract.tasks),
    )
    with pytest.raises(TemporalError, match="shared resource gpu is overallocated"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_inventory_cannot_omit_an_affecting_consumer() -> None:
    contract, row = _bucket()
    row["flows"] = row["flows"][:-1]
    row["envelopes"] = row["envelopes"][:-2]
    with pytest.raises(TemporalError, match="omits affecting task drain"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_early_overflow_is_rejected_even_when_final_inventory_would_fit() -> None:
    tasks = (_task("fill", produce=1, cost=0.01), _task("drain", consume=1, cost=0.01))
    contract, row = _contract(tasks, initial=0, capacity=10), _row(tasks)
    for index, points in ((0, [[0, 0], [1, 20]]), (2, [[0, 0], [5, 0], [6, 20]])):
        row["envelopes"][index]["lower"] = _curve(points)
        row["envelopes"][index]["upper"] = _curve(points)
    row.update(start_ms=10, end_ms=10, bound=0)
    spec = parse_temporal_spec(row)
    model = TemporalModel(spec, contract)
    final_upper = model.flow("fill").departures_upper.value(10) - model.flow("drain").departures_lower.value(10)
    assert final_upper == 0
    passed, reason = prove_temporal_bound(spec, contract)
    assert not passed
    assert "cannot exclude overflow" in reason


@pytest.mark.parametrize("nested", [False, True])
def test_finite_envelopes_cannot_support_all_time_or_nested_lookahead(nested: bool) -> None:
    contract, row = _one_flow()
    for envelope in row["envelopes"]:
        envelope["horizon_ms"] = 10
    if nested:
        row["end_ms"] = 5
        row["expression"] = {"advance": [{"advance": [{"departures_lower": "source"}, 3]}, 3]}
    with pytest.raises(TemporalError, match="time window"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_chance_union_counts_each_envelope_once_despite_repeated_curve_references() -> None:
    contract, row = _one_flow()
    row["envelopes"][0]["failure_probability_upper"] = "0.01"
    row["envelopes"][1]["failure_probability_upper"] = "0.02"
    row["expression"] = {"min": [{"departures_lower": "source"}, {"departures_lower": "source"}]}
    spec = parse_temporal_spec(row)
    assert temporal_failure_upper(spec) == Fraction(3, 100)
    contract = replace(contract, state_claims=(StateClaim("reserve", "curve_bound", spec),))
    formula = {"gte": [{"state_claim_success_probability_lower": "state-claim:reserve"}, 0.97]}
    validate_claim_formula(formula, basis="chance")
    analysis = analyze_contract(contract, (), source_fingerprint="f" * 64)
    assert evaluate_formula(formula, contract, analysis).passed
    assert not evaluate_formula({"gte": [formula["gte"][0], 0.971]}, contract, analysis).passed


def test_derived_claim_cannot_hide_probabilistic_temporal_envelopes() -> None:
    contract, row = _one_flow()
    row["envelopes"][0]["failure_probability_upper"] = 0.01
    contract = replace(contract, state_claims=(StateClaim("reserve", "curve_bound", parse_temporal_spec(row)),))
    requirements = EnglishRequirements("dagcert-english-requirements/v2", (
        EnglishClaim(
            "reserve", "The declared output bound holds under the recorded envelope assumptions.",
            ("state-claim:reserve",), assumptions=("The arrival and service premises hold jointly.",),
            basis="derived", formula={"eq": [{"state_claim_proved": "state-claim:reserve"}, 1]},
        ),
    ))
    audit = audit_translation(requirements, contract)
    assert not audit.passed
    assert any("probabilistic temporal envelopes" in finding for finding in audit.findings)


def test_consumption_lower_inventory_uses_the_largest_typed_loss() -> None:
    task = _task("drain", consume=1)
    task = replace(task, outcomes=task.outcomes + (TaskOutcome("LargeLoss", {"bucket": ResourceEffect(consume=3)}),))
    contract, row = _contract((task,), initial=20), _row((task,))
    row.update(end_ms=2, bound=11)
    spec = parse_temporal_spec(row)
    assert TemporalModel(spec, contract).expression({"inventory_lower": "bucket"}).value(2) == 11
    assert prove_temporal_bound(spec, contract)[0]
    row["bound"] = 12
    assert not prove_temporal_bound(parse_temporal_spec(row), contract)[0]


@pytest.mark.parametrize("expression", [{"magic_rate": "source"}, {"add": []}, {"constant": True}, {"shift": [{"departures_lower": "source"}, -1]}])
def test_malformed_curve_operators_fail_closed(expression: dict[str, Any]) -> None:
    contract, row = _one_flow()
    row["expression"] = expression
    assert not prove_temporal_bound(parse_temporal_spec(row), contract)[0]


@pytest.mark.parametrize("field,value", [("failure_probability_upper", "nan"), ("horizon_ms", -1), ("slots", 0)])
def test_invalid_envelope_numbers_fail_at_parse(field: str, value: Any) -> None:
    _, row = _one_flow()
    row["envelopes"][1][field] = value
    with pytest.raises(TemporalError):
        parse_temporal_spec(row)


def _pipeline() -> tuple[Contract, dict[str, Any]]:
    source, target = _task("source"), _task("target")
    target = replace(target, typed_dependencies=(TypedDependency("source", "Completed"),), depends_on=("source",))
    contract, row = _contract((source, target)), _row((source, target), expression={"departures_lower": "target"})
    row["envelopes"] = [envelope for envelope in row["envelopes"] if envelope["id"] != "arrivals-target"]
    row["flows"][1]["input"] = {"output": {
        "task": "source", "delay_ms": 2,
        "assumption": "Each source completion is delivered once to the target within two milliseconds.",
        "horizon_ms": None, "failure_probability_upper": "0.03",
    }}
    row.update(start_ms=10, end_ms=10, bound=5)
    return contract, row


def test_pipeline_output_requires_typed_edge_and_explicit_routing_premise() -> None:
    contract, row = _pipeline()
    spec = parse_temporal_spec(row)
    validate_temporal_spec(spec, contract)
    assert prove_temporal_bound(spec, contract)[0]
    assert temporal_failure_upper(spec) == Fraction(3, 100)
    row["flows"][1]["input"] = {"output": "source"}
    with pytest.raises(TemporalError, match="flow handoff must contain exactly"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_pipeline_routing_cannot_invent_a_typed_dependency() -> None:
    contract, row = _pipeline()
    contract = replace(contract, tasks=(contract.tasks[0], replace(contract.tasks[1], typed_dependencies=())))
    with pytest.raises(TemporalError, match="sole typed input"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_deconvolution_requires_interval_and_all_time_premises() -> None:
    contract, row = _one_flow()
    row.update(expression={"deconvolve": [{"arrivals_upper": "source"}, {"service_lower": "source"}]}, operator="lte", bound=2, end_ms=0)
    assert prove_temporal_bound(parse_temporal_spec(row), contract)[0]
    row["envelopes"][0]["window"] = "prefix"
    with pytest.raises(TemporalError, match="interval arrival envelopes"):
        validate_temporal_spec(parse_temporal_spec(row), contract)
    row["envelopes"][0]["window"] = "interval"
    row["envelopes"][0]["horizon_ms"] = 20
    row["end_ms"] = 10
    with pytest.raises(TemporalError, match="all-time envelope premises"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_all_time_proof_detects_negative_tail_far_beyond_a_sampled_horizon() -> None:
    contract, row = _one_flow()
    row["expression"] = {"add": [{"constant": 10}, {"subtract": [
        {"departures_lower": "source"}, {"scale": [{"arrivals_upper": "source"}, "1.000000001"]},
    ]}]}
    row["end_ms"] = 1_000_000
    assert prove_temporal_bound(parse_temporal_spec(row), contract)[0]
    row["end_ms"] = None
    passed, reason = prove_temporal_bound(parse_temporal_spec(row), contract)
    assert not passed
    assert "unbounded below" in reason


def test_source_loaded_contract_checks_and_proves_temporal_claim(project: dict[str, Any]) -> None:
    path = Path(project["contract"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["schema"] = "dagcert-contract/v7"
    task = raw["tasks"][0]
    task["start_resources"] = {}
    task["timings"] = {
        "duration": {"metric": "duration", "upper_ms": 0.5, "evidence": "assumed", "minimum_samples": 0},
        "dispatch": {"metric": "wait", "upper_ms": 0.5, "evidence": "assumed", "minimum_samples": 0},
    }
    row = _row((_task("work"),), expression={"departures_lower": "work"})
    row.update(bound=5, start_ms=10, end_ms=10)
    raw["state_claims"] = [row]
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    contract = load_contract(path)
    assert contract.tasks[0].source_signature is not None
    assert prove_temporal_bound(contract.state_claims[0].specification, contract)[0]
    invalid = deepcopy(raw)
    invalid["state_claims"][0]["flows"][0]["service"] = "does-not-exist"
    path.write_text(json.dumps(invalid, indent=2), encoding="utf-8")
    with pytest.raises(ContractError, match="own service envelope"):
        load_contract(path)


def _requirements_for_state(
    spec: dict[str, Any], formula: dict[str, Any], *, basis: str = "chance", extra_refs: tuple[str, ...] = (),
) -> EnglishRequirements:
    return EnglishRequirements("dagcert-english-requirements/v2", (EnglishClaim(
        "reserve", "The declared output bound holds with the stated joint-window probability.",
        tuple(sorted(temporal_references(spec) | {"state-claim:reserve"} | set(extra_refs))),
        assumptions=("Arrival, execution, outcome, and routing envelope events hold over the whole declared window.",),
        basis=basis, formula=formula,
    ),))


def test_outcome_envelope_conditions_on_success_without_erasing_source_failure() -> None:
    contract, row = _pipeline()
    source = contract.tasks[0]
    contract = replace(contract, tasks=(replace(source, outcomes=source.outcomes + (TaskOutcome("Failed"),)), contract.tasks[1]))
    row["flows"][1]["input"]["output"]["failure_probability_upper"] = 0
    assert not prove_temporal_bound(parse_temporal_spec(row), contract)[0]
    source_service = row["envelopes"][1]
    source_service.update(outcomes=["Completed"], failure_probability_upper="0.01")
    spec = dict(parse_temporal_spec(row))
    assert prove_temporal_bound(spec, contract)[0]
    assert set(contract.tasks[0].outcome_by_type) == {"Completed", "Failed"}
    contract = replace(contract, state_claims=(StateClaim("reserve", "curve_bound", spec),))
    probability_formula = {"gte": [{"state_claim_success_probability_lower": "state-claim:reserve"}, 0.99]}
    analysis = analyze_contract(contract, (), source_fingerprint="f" * 64)
    assert evaluate_formula(probability_formula, contract, analysis).passed
    chance_audit = audit_translation(_requirements_for_state(spec, probability_formula), contract)
    assert chance_audit.passed, chance_audit.findings
    derived_formula = {"eq": [{"state_claim_proved": "state-claim:reserve"}, 1]}
    derived_audit = audit_translation(_requirements_for_state(spec, derived_formula, basis="derived"), contract)
    assert not derived_audit.passed
    assert any("probabilistic temporal envelopes" in finding for finding in derived_audit.findings)


def test_outcome_envelope_cannot_name_a_type_absent_from_production() -> None:
    contract, row = _one_flow()
    row["envelopes"][1]["outcomes"] = ["InventedSuccess"]
    with pytest.raises(TemporalError, match="outside the source union"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_failure_inventory_effects_are_excluded_only_under_an_explicit_outcome_event() -> None:
    contract, row = _bucket()
    first = contract.tasks[0]
    failure = TaskOutcome("Failed", {"bucket": ResourceEffect(consume=10)})
    contract = replace(contract, tasks=(replace(first, outcomes=first.outcomes + (failure,)),) + contract.tasks[1:])
    assert not prove_temporal_bound(parse_temporal_spec(row), contract)[0]
    row["envelopes"][1].update(outcomes=["Completed"], failure_probability_upper="0.01")
    spec = parse_temporal_spec(row)
    assert temporal_failure_upper(spec) == Fraction(1, 100)
    assert prove_temporal_bound(spec, contract)[0]
    assert TemporalModel(spec, contract).expression({"inventory_lower": "bucket"}).infimum() == 31


def test_inventory_cannot_ignore_legacy_untyped_resource_effects() -> None:
    contract, row = _bucket()
    untyped = replace(_task("hidden_consumer"), outcomes=(), resources={"bucket": ResourceEffect(consume=1)})
    contract = replace(contract, tasks=contract.tasks + (untyped,), workers=contract.workers + (Worker(untyped.worker, 1),))
    with pytest.raises(TemporalError, match="untyped affecting task hidden_consumer"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


def test_composition_probability_cannot_cover_an_unaccounted_temporal_event() -> None:
    contract, row = _one_flow()
    row["envelopes"][0]["failure_probability_upper"] = "0.2"
    spec = dict(parse_temporal_spec(row))
    contract = replace(
        contract, state_claims=(StateClaim("reserve", "curve_bound", spec),),
        compositions=(Composition("path", (CompositionStep("source", "duration", outcome_type="Completed"),)),),
    )
    formula = {"and": [
        {"gte": [{"composition_success_probability_lower": "composition:path"}, 0.9]},
        {"lte": [{"add": [
            {"composition_upper_ms": "composition:path"}, {"state_claim_proved": "state-claim:reserve"},
        ]}, 100]},
    ]}
    # This is a structurally legal probability-plus-derived-bound formula, but
    # the composition probability does not account for the temporal event.
    validate_claim_formula(formula, basis="chance")
    audit = audit_translation(_requirements_for_state(spec, formula, extra_refs=("composition:path",)), contract)
    assert not audit.passed
    assert any("probabilistic temporal envelopes" in finding for finding in audit.findings)


def test_arithmetic_cannot_turn_a_failed_temporal_proof_into_a_passing_probability() -> None:
    contract, row = _one_flow()
    bad_row = deepcopy(row)
    bad_row.update(bound=10, end_ms=0)
    contract = replace(contract, state_claims=(
        StateClaim("good", "curve_bound", parse_temporal_spec(row)),
        StateClaim("bad", "curve_bound", parse_temporal_spec(bad_row)),
    ))
    formula = {"gte": [{"add": [
        {"state_claim_success_probability_lower": "state-claim:good"},
        {"state_claim_success_probability_lower": "state-claim:bad"},
    ]}, 1]}
    with pytest.raises(FormulaError, match="left operand must be exactly"):
        validate_claim_formula(formula, basis="chance")
    analysis = analyze_contract(contract, (), source_fingerprint="f" * 64)
    with pytest.raises(FormulaError, match="state claim bad failed"):
        evaluate_formula(formula, contract, analysis)


def test_deconvolution_requires_all_time_routing_premises_too() -> None:
    contract, row = _pipeline()
    row["flows"][1]["input"]["output"]["horizon_ms"] = 10
    row.update(
        expression={"deconvolve": [{"arrivals_upper": "target"}, {"service_lower": "target"}]},
        operator="lte", bound=2, start_ms=0, end_ms=0,
    )
    with pytest.raises(TemporalError, match="all-time.*premises"):
        validate_temporal_spec(parse_temporal_spec(row), contract)


@pytest.mark.parametrize("field", ["duration_timing", "dispatch_timing"])
@pytest.mark.parametrize("value", [[], {}, None, ""])
def test_invalid_service_timing_reference_reports_schema_error(field: str, value: Any) -> None:
    _contract, row = _one_flow()
    row["envelopes"][1][field] = value
    with pytest.raises(TemporalError, match=f"service {field} must name a timing case"):
        parse_temporal_spec(row)
