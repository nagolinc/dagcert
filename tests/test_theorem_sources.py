"""Source postconditions enter timing logic without invented facts or liveness."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from dagcert.contract import Contract, Implementation, Task, TaskOutcome, Worker
from dagcert.linear_logic import prove_implication
from dagcert.source_types import SourceSignature
from dagcert.theorem_sources import TheoremSourceError, source_binding_constraints, source_fact


def _contract(*, multiple: bool = False) -> Contract:
    fields = (("amount", "int"), ("flag", "bool"), ("rounded", "float"), ("key", "str"))
    outcomes = ("Completed", "Failed") if multiple else ("Completed",)
    signature = SourceSignature(
        "python", "operations.py", "work", "Request", outcomes, 1,
        fields, tuple((outcome, fields) for outcome in outcomes),
    )
    task = Task(
        "work", "worker", "Request", " | ".join(outcomes),
        implementation=Implementation("python", "operations.py", "work"),
        outcomes=tuple(TaskOutcome(outcome) for outcome in outcomes), source_signature=signature,
    )
    return Contract("dagcert-contract/v12", (Worker("worker", 1),), (task,), ())


def _variable(field: str, *, sort: str = "real", outcome: str = "Completed", invocation: str = "one", unit: str = "items") -> dict[str, Any]:
    return {
        "sort": sort, "unit": unit,
        "binding": {"task": "work", "invocation": invocation, "outcome": outcome, "field": field},
    }


def _variables(*, multiple: bool = False) -> dict[str, Any]:
    result = {
        "before": _variable("input.amount"),
        "after": _variable("result.amount"),
        "flag": _variable("input.flag", sort="bool", unit="boolean"),
        "done": _variable("$completed", sort="bool", unit="boolean"),
    }
    if multiple:
        result.update({
            "accepted": _variable("$selected", sort="bool", unit="boolean"),
            "failed": _variable("$selected", sort="bool", outcome="Failed", unit="boolean"),
            "failed_after": _variable("result.amount", outcome="Failed"),
        })
    return result


def _premise(predicate: str, *, outcome: str = "Completed", invocation: str = "one") -> dict[str, Any]:
    return {
        "id": "step", "kind": "source", "task": "work", "invocation": invocation,
        "outcome": outcome, "predicate": predicate,
    }


def _prove(variables: dict[str, Any], assumptions: list[str], conclusion: str) -> str:
    return prove_implication({name: row["sort"] for name, row in variables.items()}, assumptions, conclusion).status


def test_source_fact_is_mechanically_derived_from_original_proved_predicate() -> None:
    variables, contract = _variables(), _contract()
    predicate = "result.amount == input.amount + 1"
    formula, relation = source_fact(_premise(predicate), variables, contract)
    assert relation.predicate == predicate
    assert relation.task_id == "work" and relation.outcome_type == "Completed"
    constraints = source_binding_constraints(variables, contract)
    assert _prove(variables, constraints + [formula, "done"], "(= after (+ before 1))") == "valid"
    assert _prove(variables, constraints + [formula], "(= after (+ before 1))") == "invalid"


def test_postcondition_cannot_prove_its_own_completion() -> None:
    variables, contract = _variables(), _contract()
    formula, _ = source_fact(_premise("result.amount >= 0"), variables, contract)
    assert _prove(variables, source_binding_constraints(variables, contract) + [formula], "done") == "invalid"


def test_complete_outcome_union_is_conditional_on_completed_invocation() -> None:
    variables, contract = _variables(multiple=True), _contract(multiple=True)
    constraints = source_binding_constraints(variables, contract)
    assert _prove(variables, constraints + ["done"], "(xor accepted failed)") == "valid"
    assert _prove(variables, constraints + ["(not done)"], "(and (not accepted) (not failed))") == "valid"
    assert _prove(variables, constraints + ["accepted"], "done") == "valid"
    assert _prove(variables, constraints, "done") == "invalid"


def test_failed_outcome_does_not_acquire_success_postcondition() -> None:
    variables, contract = _variables(multiple=True), _contract(multiple=True)
    formula, _ = source_fact(_premise("result.amount == input.amount + 1"), variables, contract)
    constraints = source_binding_constraints(variables, contract)
    assert _prove(variables, constraints + [formula, "accepted"], "(= after (+ before 1))") == "valid"
    assert _prove(variables, constraints + [formula, "failed"], "(= after (+ before 1))") == "invalid"


def test_same_input_and_same_output_aliases_cannot_assume_different_values() -> None:
    variables, contract = _variables(multiple=True), _contract(multiple=True)
    variables["before_on_failure"] = _variable("input.amount", outcome="Failed")
    variables["after_alias"] = _variable("result.amount")
    variables["done_alias"] = _variable("$completed", sort="bool", outcome="Failed", unit="boolean")
    constraints = source_binding_constraints(variables, contract)
    assert _prove(variables, constraints, "(and (= before before_on_failure) (= after after_alias) (= done done_alias))") == "valid"
    assert _prove(variables, constraints + ["(= before 1)", "(= before_on_failure 2)"], "true") == "inconsistent"


def test_distinct_invocations_are_not_accidentally_aliased() -> None:
    variables, contract = _variables(), _contract()
    variables["before_two"] = _variable("input.amount", invocation="two")
    variables["done_two"] = _variable("$completed", sort="bool", invocation="two", unit="boolean")
    assert _prove(variables, source_binding_constraints(variables, contract), "(= before before_two)") == "invalid"


def test_single_outcome_selection_equals_completion_if_explicitly_bound() -> None:
    variables, contract = _variables(), _contract()
    variables["accepted"] = _variable("$selected", sort="bool", unit="boolean")
    assert _prove(variables, source_binding_constraints(variables, contract), "(= accepted done)") == "valid"


@pytest.mark.parametrize("missing", ["failed", "done"])
def test_omitted_outcome_or_completion_binding_is_refused(missing: str) -> None:
    variables = _variables(multiple=True)
    del variables[missing]
    with pytest.raises(TheoremSourceError, match="selected|completed"):
        source_binding_constraints(variables, _contract(multiple=True))


@pytest.mark.parametrize("predicate", [
    "0 <= result.amount <= input.amount + 3",
    "input.flag and result.amount >= 0 or not input.flag",
    "input.flag is True or result.amount == -input.amount",
    "result.amount * (2 + 1) == input.amount - -2",
    "1 == 1",
    "True",
])
def test_exact_primitive_source_predicates_translate(predicate: str) -> None:
    variables, contract = _variables(), _contract()
    formula, relation = source_fact(_premise(predicate), variables, contract)
    assert formula and relation.predicate == predicate


@pytest.mark.parametrize("predicate", [
    "result.amount == input.amount / 2",
    "result.amount == input.amount // 2",
    "result.amount == input.amount % 2",
    "result.amount == input.amount * result.amount",
    "result.amount == 1.0",
    "result.amount is input.amount",
    "input.flag == 1",
    "input.amount and result.amount",
    "not input.amount",
    "input.amount",
    "len(input.key) == result.amount",
    "input.missing == result.amount",
    "input.flag.real == result.amount",
])
def test_source_semantics_are_not_silently_replaced_by_real_arithmetic(predicate: str) -> None:
    with pytest.raises(TheoremSourceError):
        source_fact(_premise(predicate), _variables(), _contract())


@pytest.mark.parametrize(("field", "sort"), [
    ("input.rounded", "real"), ("input.key", "real"), ("input.missing", "real"),
    ("input.amount", "bool"), ("input.flag", "real"), ("$selected", "real"),
    ("$completed", "real"), ("input.inner.amount", "real"),
])
def test_source_binding_types_come_from_compiler_fields(field: str, sort: str) -> None:
    variables = _variables()
    variables["bad"] = _variable(field, sort=sort)
    with pytest.raises(TheoremSourceError):
        source_binding_constraints(variables, _contract())


def test_binding_same_field_to_different_units_is_not_a_conversion() -> None:
    variables = _variables()
    variables["renamed"] = _variable("input.amount", unit="seconds")
    with pytest.raises(TheoremSourceError, match="units"):
        source_binding_constraints(variables, _contract())


def test_contract_labels_cannot_replace_compiler_outcomes() -> None:
    contract = _contract(multiple=True)
    broken = replace(contract, tasks=(replace(contract.tasks[0], outcomes=(TaskOutcome("Completed"),)),))
    with pytest.raises(TheoremSourceError, match="compiler-extracted union"):
        source_binding_constraints(_variables(multiple=True), broken)


def test_missing_source_signature_does_not_become_an_assumption() -> None:
    contract = _contract()
    broken = replace(contract, tasks=(replace(contract.tasks[0], source_signature=None),))
    with pytest.raises(TheoremSourceError, match="compiler-bound"):
        source_fact(_premise("True"), _variables(), broken)


def test_caller_cannot_attach_different_smt_fact_to_a_source_predicate() -> None:
    premise = _premise("result.amount >= 0")
    premise["formula"] = "(<= after 1)"
    with pytest.raises(TheoremSourceError, match="source premise requires"):
        source_fact(premise, _variables(), _contract())


def test_mathematical_variables_do_not_require_invented_source_bindings() -> None:
    variables = {"parameter": {"sort": "real", "unit": "ms", "binding": None}}
    assert source_binding_constraints(variables, _contract()) == []


def test_source_fact_for_another_invocation_does_not_reuse_bound_fields() -> None:
    with pytest.raises(TheoremSourceError, match="no variable binding"):
        source_fact(_premise("result.amount == input.amount", invocation="other"), _variables(), _contract())


def test_source_fact_does_not_mutate_its_sealed_declarations() -> None:
    variables = _variables()
    original = deepcopy(variables)
    source_fact(_premise("result.amount == input.amount"), variables, _contract())
    assert variables == original
