"""Behavioral proofs and counterexamples for generic source-bound induction."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from dagcert.contract import Contract, ContractError, Implementation, StateClaim, Task, TaskOutcome, Worker
from dagcert.induction import (
    InductionError,
    induction_references,
    parse_induction_spec,
    prove_inductive_invariant,
    relation_source_obligations,
    validate_induction_spec,
    validate_joint_initialization,
)
from dagcert.source_types import SourceSignature


def _transition(task: str, outcome: str, variables: tuple[str, ...], relation: str) -> dict[str, Any]:
    return {
        "task": task, "outcome": outcome,
        "before": {name: f"input.{name}" for name in variables},
        "after": {name: f"result.{name}" for name in variables},
        "relation": relation,
    }


def _row(
    variables: tuple[str, ...], initial: str, invariant: str, transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": "state-safety", "kind": "relational_invariant",
        "variables": {name: "int" for name in variables},
        "initial": initial, "invariant": invariant, "transitions": transitions,
        "assumption": "The initial predicate holds and these atomic transitions cover every state mutation.",
        "metadata": {},
    }


def _contract(row: dict[str, Any], *, source_types: bool = True) -> Contract:
    outcomes: dict[str, list[str]] = {}
    for transition in row["transitions"]:
        outcomes.setdefault(transition["task"], []).append(transition["outcome"])
    fields = tuple((name, "int") for name in row["variables"])
    tasks = tuple(
        Task(
            name, "worker", "State", " | ".join(variants),
            implementation=Implementation("python", "operations.py", name),
            outcomes=tuple(TaskOutcome(variant) for variant in variants),
            source_signature=SourceSignature(
                "python", "operations.py", name, "State", tuple(variants), 1,
                fields, tuple((variant, fields) for variant in variants),
            ) if source_types else None,
        )
        for name, variants in outcomes.items()
    )
    return Contract("dagcert-contract/v12", (Worker("worker", 1),), tasks, ())


def _prove(row: dict[str, Any]) -> tuple[bool, str]:
    return prove_inductive_invariant(parse_induction_spec(row), _contract(row))


def _buffer() -> dict[str, Any]:
    variables = ("fill",)
    return _row(variables, "state.fill == 0", "0 <= state.fill <= 30", [
        _transition("put", "Accepted", variables, "before.fill < 30 and after.fill == before.fill + 1"),
        _transition("put", "Full", variables, "after.fill == before.fill"),
        _transition("take", "Taken", variables, "before.fill > 0 and after.fill == before.fill - 1"),
        _transition("take", "Empty", variables, "after.fill == before.fill"),
    ])


def test_bounded_buffer_invariant_covers_admit_full_take_and_empty() -> None:
    assert _prove(_buffer())[0]


def test_broken_buffer_admission_returns_real_overflow_counterexample() -> None:
    row = _buffer()
    row["transitions"][0]["relation"] = "after.fill == before.fill + 1"
    passed, message = _prove(row)
    assert not passed
    assert "before.fill=30" in message and "after.fill=31" in message


def test_latest_version_can_ignore_stale_responses_without_regressing_display() -> None:
    variables = ("latest", "shown", "previous")
    row = _row(
        variables, "state.latest == 0 and state.shown == 0 and state.previous == 0",
        "0 <= state.previous <= state.shown <= state.latest", [
            _transition("submit", "Submitted", variables,
                        "after.latest == before.latest + 1 and after.shown == before.shown "
                        "and after.previous == before.shown"),
            _transition("response", "Published", variables,
                        "after.latest == before.latest and after.shown == before.latest "
                        "and after.previous == before.shown"),
            _transition("response", "Stale", variables,
                        "after.latest == before.latest and after.shown == before.shown "
                        "and after.previous == before.previous"),
        ],
    )
    assert _prove(row)[0]
    row["transitions"][1]["relation"] = (
        "after.latest == before.latest and after.shown == before.previous "
        "and after.previous == before.shown"
    )
    passed, message = _prove(row)
    assert not passed and "response/Published" in message


def test_duplicate_acknowledgements_cannot_manufacture_distinct_progress() -> None:
    variables = ("unique", "credited")
    row = _row(variables, "state.unique == 0 and state.credited == 0",
               "state.unique == state.credited and state.unique >= 0", [
        _transition("ack", "New", variables,
                    "after.unique == before.unique + 1 and after.credited == before.credited + 1"),
        _transition("ack", "Duplicate", variables,
                    "after.unique == before.unique and after.credited == before.credited"),
    ])
    assert _prove(row)[0]
    row["transitions"][1]["relation"] = (
        "after.unique == before.unique and after.credited == before.credited + 1"
    )
    passed, message = _prove(row)
    assert not passed and "ack/Duplicate" in message


def test_keyed_join_requires_matching_identities_not_healthy_totals() -> None:
    variables = ("audio", "video", "published", "key")
    row = _row(
        variables, "state.audio == 0 and state.video == 0 and state.published == 0 and state.key == 0",
        "state.published == 0 or (state.audio == state.video and state.key == state.audio)", [
            _transition("audio", "Arrived", variables,
                        "after.audio == before.audio + 1 and after.video == before.video "
                        "and after.published == 0 and after.key == before.key"),
            _transition("video", "Arrived", variables,
                        "after.audio == before.audio and after.video == before.video + 1 "
                        "and after.published == 0 and after.key == before.key"),
            _transition("join", "Matched", variables,
                        "before.audio == before.video and after.audio == before.audio "
                        "and after.video == before.video and after.published == 1 and after.key == before.audio"),
            _transition("join", "Pending", variables,
                        "after.audio == before.audio and after.video == before.video "
                        "and after.published == 0 and after.key == before.key"),
        ],
    )
    assert _prove(row)[0]
    row["transitions"][2]["relation"] = row["transitions"][2]["relation"].replace(
        "before.audio == before.video and ", "",
    )
    passed, message = _prove(row)
    assert not passed and "join/Matched" in message


def test_unsatisfiable_initial_state_is_not_a_certificate() -> None:
    row = _buffer()
    row["initial"] = "state.fill < 0 and state.fill >= 0"
    assert _prove(row) == (False, "initial state predicate is unsatisfiable; refusing a vacuous invariant")


def test_initial_state_must_imply_invariant() -> None:
    row = _buffer()
    row["initial"] = "state.fill == 31"
    passed, message = _prove(row)
    assert not passed and "state.fill=31" in message


def test_unreachable_typed_outcome_does_not_require_invented_failure() -> None:
    row = _buffer()
    row["transitions"][1]["relation"] = "False"
    assert _prove(row)[0]  # Separate source proof must prove this outcome unreachable.


def test_all_real_source_outcomes_must_be_included() -> None:
    row = _buffer()
    contract = _contract(row)
    row["transitions"].pop(1)
    passed, message = prove_inductive_invariant(parse_induction_spec(row), contract)
    assert not passed and "missing ['Full']" in message


def test_implementation_outcome_union_cannot_be_relabelled() -> None:
    row = _buffer()
    contract = _contract(row)
    task = contract.tasks[0]
    assert task.source_signature is not None
    altered = replace(task, source_signature=replace(task.source_signature, outcome_types=("Accepted", "Full", "Failure")))
    contract = replace(contract, tasks=(altered, *contract.tasks[1:]))
    passed, message = prove_inductive_invariant(parse_induction_spec(row), contract)
    assert not passed and "disagrees with real source types" in message


def test_source_obligations_cover_every_outcome_and_clear_fractional_coefficients() -> None:
    variables = ("value",)
    row = _row(variables, "state.value == 0", "state.value >= 0", [
        _transition("step", "Done", variables, "after.value / 3 == before.value + 0.1"),
        _transition("step", "Skipped", variables, "after.value == before.value"),
    ])
    obligations = relation_source_obligations(parse_induction_spec(row), _contract(row))
    assert len(obligations) == 2
    assert {item.outcome_type for item in obligations} == {"Done", "Skipped"}
    assert obligations[0].predicate == "10 * result.value + -30 * input.value + -3 == 0"
    assert obligations[1].predicate == "result.value + -1 * input.value == 0"
    # Rational specification arithmetic is NOT inserted as Python float division.


def test_model_check_without_signatures_is_not_claimed_as_source_proof() -> None:
    row = _buffer()
    passed, message = prove_inductive_invariant(parse_induction_spec(row), _contract(row, source_types=False))
    assert passed and "conditional on verified source transition relations" in message


def test_numeric_source_field_must_exist() -> None:
    row = _buffer()
    row["transitions"][0]["before"]["fill"] = "input.missing"
    passed, message = _prove(row)
    assert not passed and "input.missing" in message


def test_float_is_not_silently_treated_as_exact_real() -> None:
    row = _buffer()
    row["variables"]["fill"] = "real"
    contract = _contract(row)
    task = contract.tasks[0]
    assert task.source_signature is not None
    altered = replace(task, source_signature=replace(task.source_signature, input_fields=(("fill", "float"),)))
    contract = replace(contract, tasks=(altered, *contract.tasks[1:]))
    passed, message = prove_inductive_invariant(parse_induction_spec(row), contract)
    assert not passed and "IEEE float/number" in message


def test_integer_source_can_be_embedded_in_real_model() -> None:
    row = _buffer()
    row["variables"]["fill"] = "real"
    # Real-valued fill could lie at 29.5, so preserve only with a full unit free.
    row["transitions"][0]["relation"] = "before.fill <= 29 and after.fill == before.fill + 1"
    row["transitions"][2]["relation"] = "before.fill >= 1 and after.fill == before.fill - 1"
    assert _prove(row)[0]


@pytest.mark.parametrize("predicate", [
    "state.fill * state.fill >= 0",
    "state.fill / state.fill == 1",
    "state.fill / 0 == 0",
    "len(state.fill) > 0",
    "__import__('os').system('whoami') == 0",
    "state.missing >= 0",
    "input.fill >= 0",
    "state.fill ** 2 >= 0",
    "state.fill // 2 >= 0",
    "state.fill % 2 == 0",
    "state.fill is None",
    "state.fill >= 1e999",
])
def test_unsupported_or_executable_predicates_are_rejected(predicate: str) -> None:
    row = _buffer()
    row["invariant"] = predicate
    with pytest.raises(InductionError):
        parse_induction_spec(row)


def test_arbitrary_boolean_pass_flags_are_not_state_types() -> None:
    row = _buffer()
    row["variables"]["fill"] = "bool"
    with pytest.raises(InductionError, match="not arbitrary booleans"):
        parse_induction_spec(row)


def test_explicit_initialization_and_closed_scope_premise_required() -> None:
    row = _buffer()
    row["assumption"] = ""
    with pytest.raises(InductionError, match="initial-state and complete mutation-scope"):
        parse_induction_spec(row)


def test_unknown_solver_result_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from dagcert import induction

    class UnknownSolver:
        def add(self, *_arguments: Any) -> None:
            pass

        def check(self) -> Any:
            return induction.z3.unknown

        def reason_unknown(self) -> str:
            return "test interruption"

    monkeypatch.setattr(induction.z3, "Solver", UnknownSolver)
    passed, message = _prove(_buffer())
    assert not passed and "unknown: test interruption" in message


def test_binding_maps_must_cover_all_variables_and_use_correct_namespaces() -> None:
    row = _buffer()
    del row["transitions"][0]["after"]["fill"]
    with pytest.raises(InductionError, match="exactly"):
        parse_induction_spec(row)
    row = _buffer()
    row["transitions"][0]["after"]["fill"] = "input.fill"
    with pytest.raises(InductionError, match="result"):
        parse_induction_spec(row)


def test_duplicate_transition_and_unknown_task_are_rejected() -> None:
    row = _buffer()
    row["transitions"].append(deepcopy(row["transitions"][0]))
    with pytest.raises(InductionError, match="duplicate"):
        parse_induction_spec(row)
    row = _buffer()
    contract = _contract(row)
    row["transitions"][0]["task"] = "missing"
    with pytest.raises(InductionError, match="unknown task"):
        validate_induction_spec(parse_induction_spec(row), contract)


def test_observer_cannot_stand_in_for_state_transition() -> None:
    row = _buffer()
    contract = _contract(row)
    contract = replace(contract, tasks=(replace(contract.tasks[0], role="instrumentation"), *contract.tasks[1:]))
    passed, message = prove_inductive_invariant(parse_induction_spec(row), contract)
    assert not passed and "source-owned operation" in message


def test_references_bind_all_mutating_tasks() -> None:
    assert induction_references(parse_induction_spec(_buffer())) == {"task:put", "task:take"}


def _claim(row: dict[str, Any], identifier: str) -> StateClaim:
    return StateClaim(identifier, "relational_invariant", parse_induction_spec(row))


def test_shared_source_initial_values_must_be_jointly_satisfiable() -> None:
    first, second = _buffer(), _buffer()
    second["initial"] = "state.fill == 5"
    contract = _contract(first)
    assert _prove(first)[0] and _prove(second)[0]
    claims = (_claim(first, "empty"), _claim(second, "warm"))
    with pytest.raises(InductionError, match="empty, warm"):
        validate_joint_initialization(claims, contract)


def test_renaming_variables_does_not_hide_shared_source_initial_conflict() -> None:
    first = _buffer()
    second = _row(("reserve",), "state.reserve == 5", "0 <= state.reserve <= 30", [
        {"task": transition["task"], "outcome": transition["outcome"],
         "before": {"reserve": "input.fill"}, "after": {"reserve": "result.fill"},
         "relation": transition["relation"].replace(".fill", ".reserve")}
        for transition in first["transitions"]
    ])
    with pytest.raises(InductionError, match="contradict shared source bindings"):
        validate_joint_initialization((_claim(first, "empty"), _claim(second, "warm")), _contract(first))


def test_distinct_task_instances_do_not_alias_similarly_named_fields() -> None:
    first, second = _buffer(), _buffer()
    second["initial"] = "state.fill == 5"
    for transition in second["transitions"]:
        transition["task"] += "_other"
    first_contract, second_contract = _contract(first), _contract(second)
    contract = replace(first_contract, tasks=first_contract.tasks + second_contract.tasks)
    validate_joint_initialization((_claim(first, "empty"), _claim(second, "warm")), contract)


def test_joint_initialization_follows_transitive_state_bindings() -> None:
    shared = _buffer()
    shared["initial"] = "0 <= state.fill <= 30"
    producer, consumer = deepcopy(shared), deepcopy(shared)
    producer["initial"] = "state.fill == 0"
    producer["transitions"] = [item for item in producer["transitions"] if item["task"] == "put"]
    consumer["initial"] = "state.fill == 5"
    consumer["transitions"] = [item for item in consumer["transitions"] if item["task"] == "take"]
    with pytest.raises(InductionError, match="contradict shared source bindings"):
        validate_joint_initialization(
            (_claim(shared, "shared"), _claim(producer, "producer"), _claim(consumer, "consumer")),
            _contract(shared),
        )


def test_compatible_initial_ranges_allow_prepared_reserve() -> None:
    first, second = _buffer(), _buffer()
    first["initial"] = "0 <= state.fill <= 30"
    second["initial"] = "state.fill == 5"
    validate_joint_initialization((_claim(first, "range"), _claim(second, "warm")), _contract(first))


def test_joint_initialization_unknown_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from dagcert import induction

    class UnknownSolver:
        def assert_and_track(self, *_arguments: Any) -> None:
            pass

        def check(self) -> Any:
            return induction.z3.unknown

        def reason_unknown(self) -> str:
            return "test interruption"

    row = _buffer()
    monkeypatch.setattr(induction.z3, "Solver", UnknownSolver)
    with pytest.raises(InductionError, match="joint initialization satisfiability unknown"):
        validate_joint_initialization((_claim(row, "test"),), _contract(row))


def test_contract_validation_enforces_joint_initialization() -> None:
    from dagcert.contract import _validate

    first, second = _buffer(), _buffer()
    second["initial"] = "state.fill == 5"
    contract = replace(_contract(first), state_claims=(_claim(first, "empty"), _claim(second, "warm")))
    with pytest.raises(ContractError, match="joint initial-state predicates contradict"):
        _validate(contract)
