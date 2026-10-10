"""Generic network-model proofs must retain physical/source/bound provenance."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from dagcert.contract import Contract, Implementation, StateClaim, Task, TaskOutcome, Worker
from dagcert.induction import parse_induction_spec
from dagcert.networks import (
    NetworkError, NetworkModel, network_references, network_relations,
    parse_network_spec, prove_network_bound,
)
from dagcert.source_types import SourceSignature


def _curve(burst: int | str = 0, rate: int | str = 0) -> dict[str, Any]:
    return {"points": [[0, burst]], "tail_slope": rate}


def _envelope(identifier: str, kind: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": identifier, "kind": kind,
        "assumption": f"The source-bound {identifier} premise holds over every stated interval.",
        "horizon_ms": None, "failure_probability_upper": 0,
        **fields,
    }


def _task(name: str, worker: str | None = None) -> Task:
    fields = (("quantity", "int"), ("batches", "int"), ("fill", "int"))
    return Task(
        name, worker or name, "Request", "Completed | Failed",
        implementation=Implementation("python", "operations.py", name),
        outcomes=(TaskOutcome("Completed"), TaskOutcome("Failed")),
        source_signature=SourceSignature(
            "python", "operations.py", name, "Request", ("Completed", "Failed"), 1,
            fields, (("Completed", fields), ("Failed", fields)),
        ),
    )


def _contract(*tasks: Task) -> Contract:
    return Contract("dagcert-contract/v12", tuple(Worker(name, 1) for name in sorted({task.worker for task in tasks})), tasks, ())


def _row(envelopes: list[dict[str, Any]], expression: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "network-bound", "kind": "curve_bound",
        "network": {"envelopes": envelopes, "relations": [], "invariants": []},
        "expression": expression, "operator": "gte", "bound": 0,
        "start_ms": 0, "end_ms": None, "metadata": {},
    }


def _worker(task: str = "produce", worker: str | None = None, tasks: list[str] | None = None) -> dict[str, Any]:
    return _envelope("server", "worker", worker=worker or task, tasks=tasks or [task], slots=1, availability=_curve(rate=1))


def _workload(task: str = "produce", identifier: str = "cost") -> dict[str, Any]:
    return _envelope(
        identifier, "workload", task=task, unit="playable_ms",
        outcome_quantities={"Completed": "result.quantity", "Failed": 0},
        work_per_quantity="2/3", excess_work=6, unfinished_work=12,
    )


def _arrival(task: str, identifier: str, *, unit: str = "playable_ms", field: str = "quantity", rate: int | str = 1) -> dict[str, Any]:
    return _envelope(identifier, "arrival", task=task, input_field=field, unit=unit,
                     lower=_curve(rate=rate), upper=_curve(1, rate), window="interval")


def _service(work: dict[str, Any] | None = None, workload: str = "cost") -> dict[str, Any]:
    return {"quantity_service": {"work": work or {"worker_service": "server"}, "workload": workload}}


def _constant(value: int, unit: str = "playable_ms") -> dict[str, Any]:
    return {"constant": {"value": value, "unit": unit}}


def _prove(row: dict[str, Any], contract: Contract) -> tuple[bool, str]:
    return prove_network_bound(parse_network_spec(row), contract)


def _streaming() -> tuple[dict[str, Any], Contract]:
    controller = _task("control")
    invariant = parse_induction_spec({
        "id": "bounded-buffer", "kind": "relational_invariant",
        "variables": {"fill": "int"}, "initial": "state.fill == 30",
        "invariant": "0 <= state.fill <= 100",
        "transitions": [
            {"task": "control", "outcome": outcome,
             "before": {"fill": "input.fill"}, "after": {"fill": "result.fill"},
             "relation": "0 <= after.fill <= 100"}
            for outcome in ("Completed", "Failed")
        ],
        "assumption": "This controller owns all buffer mutations and starts with 30 units.", "metadata": {},
    })
    contract = replace(_contract(_task("produce"), _task("consume"), controller), state_claims=(
        StateClaim("bounded-buffer", "relational_invariant", invariant),
    ))
    deficit = {"service_deficit": {
        "demand": {"arrival_upper": "consumption"}, "service": _service(), "policy": "refill",
    }}
    row = _row([
        _worker(), _workload(), _arrival("consume", "consumption"),
        _envelope("refill", "policy", task="control", mode="busy_period", restart_delay_ms=2),
    ], {"subtract": [_constant(30), {"max": [_constant(0), deficit]}]})
    row["network"]["invariants"] = ["bounded-buffer"]
    row["bound"] = 9
    return row, contract


def test_infinite_variable_sized_streaming_with_some_slower_than_playback_jobs() -> None:
    row, contract = _streaming()
    passed, diagnostic = _prove(row, contract)
    assert passed, diagnostic
    assert "extremum=9" in diagnostic
    # Repeating costs (12, 8) for playable durations (10, 20): individual
    # slow generation is allowed, while cumulative cost/output is 2/3 with
    # a bounded excess. The model counts playable duration, not turns.
    assert 12 > 10 and Fraction(12 + 8, 10 + 20) == Fraction(2, 3)
    row["bound"] = 10
    assert not _prove(row, contract)[0]


def test_restart_delay_is_not_omitted_from_busy_period_depletion() -> None:
    row, contract = _streaming()
    row["network"]["envelopes"][-1]["restart_delay_ms"] = 20
    passed, diagnostic = _prove(row, contract)
    assert not passed and "extremum=-9" in diagnostic


def test_busy_period_claim_needs_real_controller_invariant() -> None:
    row, contract = _streaming()
    row["network"]["invariants"] = []
    passed, diagnostic = _prove(row, contract)
    assert not passed and "controller invariant" in diagnostic


def test_worker_capacity_needs_actual_ingress_to_derive_departures() -> None:
    row = _row([_worker(), _workload(), _arrival("produce", "input", rate=2)], {
        "convolve": [{"arrival_lower": "input"}, _service()],
    })
    row.update(start_ms=20, end_ms=100, bound=3)
    assert _prove(row, _contract(_task("produce")))[0]
    row["network"]["envelopes"][-1]["lower"] = _curve()
    assert not _prove(row, _contract(_task("produce")))[0]


def test_service_alone_cannot_certify_output_or_be_laundered_with_arithmetic() -> None:
    contract = _contract(_task("produce"))
    row = _row([_worker(), _workload()], _service())
    passed, diagnostic = _prove(row, contract)
    assert not passed and "service capacity is not actual production" in diagnostic
    row["expression"] = {"add": [_constant(30), _service()]}
    passed, diagnostic = _prove(row, contract)
    assert not passed and "laundered" in diagnostic
    row["expression"] = {"subtract": [_constant(30), _service()]}
    assert not _prove(row, contract)[0]
    row["expression"] = {"scale": [_service(), 2]}
    assert not _prove(row, contract)[0]


def test_shared_worker_cannot_be_fully_allocated_to_each_task() -> None:
    contract = _contract(_task("produce", "gpu"), _task("other", "gpu"))
    row = _row([_worker(worker="gpu", tasks=["produce", "other"]), _workload()], _service())
    passed, diagnostic = _prove(row, contract)
    assert not passed and "shared worker cannot be given in full" in diagnostic


def test_one_reservation_table_allows_two_real_tasks_to_share_worker() -> None:
    contract = _contract(_task("produce", "gpu"), _task("other", "gpu"))
    allocation = _envelope("allocation", "allocation", server="server",
                           shares={"produce": "1/2", "other": "1/2"}, lag_work={"produce": 0, "other": 0})
    row = _row([
        _worker(worker="gpu", tasks=["produce", "other"]), allocation,
        _workload(), _workload("other", "other-cost"),
        _arrival("produce", "input", rate=2), _arrival("other", "other-input", rate=2),
    ], {"add": [
        {"convolve": [{"arrival_lower": "input"}, _service({"reserved_service": {"allocation": "allocation", "task": "produce"}})]},
        {"convolve": [{"arrival_lower": "other-input"}, _service({"reserved_service": {"allocation": "allocation", "task": "other"}}, "other-cost")]},
    ]})
    row.update(start_ms=100, end_ms=200, bound=96)
    assert _prove(row, contract)[0]
    row["network"]["envelopes"][1]["shares"] = {"produce": 1, "other": 1}
    passed, diagnostic = _prove(row, contract)
    assert not passed and "exceed" in diagnostic


def test_independent_allocation_tables_cannot_double_reserve_one_server() -> None:
    contract = _contract(_task("produce", "gpu"), _task("other", "gpu"))
    row = _row([
        _worker(worker="gpu", tasks=["produce", "other"]),
        _envelope("one", "allocation", server="server", shares={"produce": 1, "other": 0}, lag_work={"produce": 0, "other": 0}),
        _envelope("two", "allocation", server="server", shares={"produce": 0, "other": 1}, lag_work={"produce": 0, "other": 0}),
    ], _constant(0))
    passed, diagnostic = _prove(row, contract)
    assert not passed and "independently allocated" in diagnostic


def test_available_work_cannot_use_another_tasks_cheaper_workload() -> None:
    contract = _contract(_task("produce"), _task("other"))
    row = _row([_worker(), _workload("other")], _service())
    passed, diagnostic = _prove(row, contract)
    assert not passed and "workload must match" in diagnostic


def test_outcome_quantities_must_cover_failure_as_well_as_success() -> None:
    row, contract = _streaming()
    del row["network"]["envelopes"][1]["outcome_quantities"]["Failed"]
    passed, diagnostic = _prove(row, contract)
    assert not passed and "every source outcome" in diagnostic


def test_all_nonproducing_outcomes_cannot_supply_positive_useful_service() -> None:
    row, contract = _streaming()
    row["network"]["envelopes"][1]["outcome_quantities"] = {"Completed": 0, "Failed": 0}
    passed, _diagnostic = _prove(row, contract)
    assert not passed


def test_missing_production_outcome_field_is_rejected() -> None:
    row, contract = _streaming()
    row["network"]["envelopes"][1]["outcome_quantities"]["Completed"] = "result.invented"
    passed, diagnostic = _prove(row, contract)
    assert not passed and "numeric source field" in diagnostic


def test_finite_envelope_cannot_support_infinite_streaming() -> None:
    row, contract = _streaming()
    row["network"]["envelopes"][0]["horizon_ms"] = 1000
    passed, diagnostic = _prove(row, contract)
    assert not passed and "does not cover" in diagnostic


def test_service_and_consumption_units_must_agree() -> None:
    row, contract = _streaming()
    row["network"]["envelopes"][2]["unit"] = "turns"
    passed, diagnostic = _prove(row, contract)
    assert not passed and "matching strict usable service units" in diagnostic


def test_arrival_upper_does_not_become_a_lower_production_guarantee() -> None:
    row = _row([_arrival("produce", "input")], {"arrival_upper": "input"})
    passed, diagnostic = _prove(row, _contract(_task("produce")))
    assert not passed and "requires a lower bound" in diagnostic


def test_ordinary_residual_is_not_silently_promoted_to_strict_quantity_service() -> None:
    contract = _contract(_task("produce", "gpu"), _task("other", "gpu"))
    residual = {"leftover_service": {
        "server": {"worker_service": "server"}, "cross_demand": {"arrival_upper": "cross"},
        "blocking_work": 2, "policy": "scheduler",
    }}
    row = _row([
        _worker(worker="gpu", tasks=["produce", "other"]), _workload(),
        _arrival("other", "cross", unit="worker_ms", rate="1/4"),
        _envelope("scheduler", "policy", task="produce", mode="arbitrary", interferers=["other"]),
    ], _service(residual))
    passed, diagnostic = _prove(row, contract)
    assert not passed and "ordinary residual service is not a strict" in diagnostic
    model = NetworkModel(parse_network_spec(row), contract)
    assert model.expression(residual).kind == "work_service"


def test_residual_cannot_ignore_competing_task_or_use_wrong_demand_source() -> None:
    contract = _contract(_task("produce", "gpu"), _task("other", "gpu"))
    residual = {"leftover_service": {
        "server": {"worker_service": "server"}, "cross_demand": {"arrival_upper": "cross"},
        "blocking_work": 0, "policy": "scheduler",
    }}
    row = _row([
        _worker(worker="gpu", tasks=["produce", "other"]),
        _arrival("other", "cross", unit="worker_ms", rate="1/4"),
        _envelope("scheduler", "policy", task="produce", mode="arbitrary", interferers=[]),
    ], residual)
    passed, diagnostic = _prove(row, contract)
    assert not passed and "every competing source task" in diagnostic
    row["network"]["envelopes"][-1]["interferers"] = ["other"]
    row["network"]["envelopes"][1]["task"] = "produce"
    passed, diagnostic = _prove(row, contract)
    assert not passed and "exactly the declared interfering tasks" in diagnostic


def _batch() -> tuple[dict[str, Any], Contract]:
    row = _row([
        _arrival("batch", "quantity", unit="bytes"),
        _arrival("batch", "batches", unit="count", field="batches"),
        _envelope("flush", "policy", task="batch", mode="batching"),
    ], {"batch_work": {"input": {"arrival_upper": "quantity"}, "batches": {"arrival_upper": "batches"},
                       "unit_cost": 1, "batch_cost": 10, "flush_ms": 2, "policy": "flush"}})
    row.update(operator="lte", end_ms=10, bound=123)
    return row, _contract(_task("batch"))


def test_batch_work_includes_partial_release_count_and_timed_flush_jitter() -> None:
    row, contract = _batch()
    assert _prove(row, contract)[0]
    row["bound"] = 122
    assert not _prove(row, contract)[0]


def test_maximum_batch_size_cannot_divide_away_partial_batch_overhead() -> None:
    row, contract = _batch()
    row["expression"]["batch_work"]["batches"] = {"scale": [{"arrival_upper": "batches"}, "1/16"]}
    passed, diagnostic = _prove(row, contract)
    assert not passed and "actual partial-batch release counts" in diagnostic


def test_batch_lookahead_extends_only_needed_finite_horizon() -> None:
    row, contract = _batch()
    row["network"]["envelopes"][0]["horizon_ms"] = 12
    row["network"]["envelopes"][1]["horizon_ms"] = 10
    row["network"]["envelopes"][2]["horizon_ms"] = 10
    assert _prove(row, contract)[0]
    row["network"]["envelopes"][0]["horizon_ms"] = 11
    assert not _prove(row, contract)[0]


def test_deconvolution_requires_all_time_premises_even_for_finite_claim_window() -> None:
    row = _row([_worker(), _workload(), _arrival("produce", "input", rate=1)], {
        "deconvolve": [{"arrival_upper": "input"}, _service()],
    })
    row.update(operator="lte", end_ms=10, bound=100)
    assert _prove(row, _contract(_task("produce")))[0]
    row["network"]["envelopes"][0]["horizon_ms"] = 10
    assert not _prove(row, _contract(_task("produce")))[0]


def test_composition_checks_outer_envelope_at_the_actual_inner_time_range() -> None:
    outer = _arrival("outer", "outer", unit="count")
    inner = _arrival("inner", "inner", unit="ms", rate=2)
    outer["horizon_ms"] = 100
    inner["horizon_ms"] = 100
    row = _row([outer, inner], {"compose": [{"arrival_lower": "outer"}, {"arrival_lower": "inner"}]})
    row.update(end_ms=100)
    contract = _contract(_task("outer"), _task("inner"))
    passed, diagnostic = _prove(row, contract)
    assert not passed and "does not cover" in diagnostic
    outer["horizon_ms"] = 200
    assert _prove(row, contract)[0]


def test_network_generates_real_source_relations_and_references() -> None:
    row, contract = _streaming()
    spec = parse_network_spec(row)
    relations = network_relations(spec, contract)
    assert len(relations) == 1 and relations[0].task_id == "produce"
    assert relations[0].outcome_type == "Completed"
    assert network_references(spec) == {"task:produce", "task:consume", "task:control", "state-claim:bounded-buffer"}


def test_withheld_stock_can_drop_when_a_missing_predecessor_finishes() -> None:
    withheld = _envelope("gap", "withheld", task="produce", unit="playable_ms",
                         upper={"points": [[0, 10], [50, 10], [100, 0]], "tail_slope": 0})
    row = _row([_worker(), _workload(), _arrival("produce", "input", rate=2), withheld], {
        "ordered_prefix": [
            {"convolve": [{"arrival_lower": "input"}, _service()]},
            {"withheld_upper": "gap"},
        ],
    })
    row.update(start_ms=100, end_ms=200, bound=123)
    assert _prove(row, _contract(_task("produce")))[0]


def test_repeated_completed_quantity_is_only_a_numeric_functional_not_extra_production() -> None:
    departure = {"convolve": [{"arrival_lower": "input"}, _service()]}
    row = _row([_worker(), _workload(), _arrival("produce", "input", rate=2)], {
        "add": [departure, departure],
    })
    row.update(start_ms=100, end_ms=200, bound=246)
    contract = _contract(_task("produce"))
    passed, diagnostic = _prove(row, contract)
    assert passed and "derived numeric functional" in diagnostic
    model = NetworkModel(parse_network_spec(row), contract)
    signal = model.expression(row["expression"])
    assert signal.kind == "quantity" and signal.identity is None
    row["network"]["envelopes"].append(_envelope(
        "gap", "withheld", task="produce", unit="playable_ms", upper=_curve(),
    ))
    row["expression"] = {"ordered_prefix": [row["expression"], {"withheld_upper": "gap"}]}
    passed, diagnostic = _prove(row, contract)
    assert not passed and "matching completed lower" in diagnostic


def test_minimum_of_distinct_streams_does_not_become_a_source_matched_prefix() -> None:
    server_a, server_b = _worker("audio"), _worker("video")
    server_b["id"] = "video-server"
    audio = {"convolve": [{"arrival_lower": "audio-input"}, _service()]}
    video = {"convolve": [
        {"arrival_lower": "video-input"},
        _service({"worker_service": "video-server"}, "video-cost"),
    ]}
    row = _row([
        server_a, server_b, _workload("audio"), _workload("video", "video-cost"),
        _arrival("audio", "audio-input", rate=2), _arrival("video", "video-input", rate=2),
    ], {"min": [audio, video]})
    contract = _contract(_task("audio"), _task("video"))
    row.update(start_ms=100, end_ms=200, bound=123)
    passed, diagnostic = _prove(row, contract)
    assert passed and "derived numeric functional" in diagnostic
    signal = NetworkModel(parse_network_spec(row), contract).expression(row["expression"])
    assert signal.kind == "quantity" and signal.identity is None
    row["network"]["envelopes"].append(_envelope(
        "gap", "withheld", task="audio", unit="playable_ms", upper=_curve(),
    ))
    row["expression"] = {"ordered_prefix": [row["expression"], {"withheld_upper": "gap"}]}
    assert not _prove(row, contract)[0]


def test_scaled_up_lower_bound_cannot_be_used_as_actual_completed_quantity() -> None:
    departure = {"convolve": [{"arrival_lower": "input"}, _service()]}
    row = _row([
        _worker(), _workload(), _arrival("produce", "input", rate=2),
        _envelope("gap", "withheld", task="produce", unit="playable_ms", upper=_curve()),
    ], {"ordered_prefix": [{"scale": [departure, 2]}, {"withheld_upper": "gap"}]})
    passed, diagnostic = _prove(row, _contract(_task("produce")))
    assert not passed and "matching completed lower" in diagnostic


@pytest.mark.parametrize("mutate", [
    lambda row: row["network"]["envelopes"][0].update(kind=[]),
    lambda row: row["network"]["envelopes"][0].update(tasks=[{}]),
    lambda row: row["network"].update(invariants=[{}]),
    lambda row: row["network"]["envelopes"][1].update(work_per_quantity=[]),
    lambda row: row["network"]["envelopes"][2].update(upper={"points": [[0, []]], "tail_slope": 0}),
])
def test_malformed_inputs_have_actionable_errors_not_python_type_crashes(mutate: Any) -> None:
    row, _ = _streaming()
    mutate(row)
    with pytest.raises(NetworkError):
        parse_network_spec(row)


def test_unused_envelopes_and_duplicate_workers_are_not_hidden() -> None:
    row, contract = _streaming()
    unused = deepcopy(row["network"]["envelopes"][2])
    unused["id"] = "unused"
    row["network"]["envelopes"].append(unused)
    passed, diagnostic = _prove(row, contract)
    assert not passed and "unused network envelopes" in diagnostic
    row, contract = _streaming()
    duplicate = deepcopy(row["network"]["envelopes"][0])
    duplicate["id"] = "duplicate"
    row["network"]["envelopes"].append(duplicate)
    passed, diagnostic = _prove(row, contract)
    assert not passed and "each physical worker once" in diagnostic
