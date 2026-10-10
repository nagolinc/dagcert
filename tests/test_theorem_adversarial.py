"""Adversarial compositional proof tests independent of the primary examples."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from dagcert.contract import Contract, Implementation, StateClaim, Task, TaskOutcome, Worker
from dagcert.semantic import contract_relations
from dagcert.source_types import SourceSignature
from dagcert.theorems import TheoremError, parse_theorem_spec, prove_theorem


def _variable(task: str, field: str, *, invocation: str = "call", outcome: str = "Done") -> dict[str, Any]:
    boolean = field.startswith("$")
    return {
        "sort": "bool" if boolean else "real",
        "unit": "boolean" if boolean else "item",
        "binding": {"task": task, "invocation": invocation, "outcome": outcome, "field": field},
    }


def _row(identifier: str, *, task: str = "advance") -> dict[str, Any]:
    return {
        "id": identifier, "kind": "lra_theorem", "mode": "source",
        "variables": {
            "before": _variable(task, "input.value"),
            "after": _variable(task, "result.value"),
            "done": _variable(task, "$completed"),
        },
        "premises": [
            {"id": "step", "kind": "source", "task": task, "invocation": "call", "outcome": "Done",
             "predicate": "result.value == input.value + 1"},
            {"id": "arrival", "kind": "envelope", "formula": "(and done (>= before 0))",
             "assumption": "This completed invocation receives a nonnegative input under the declared envelope.",
             "event": "arrival-and-completion", "horizon_ms": 100, "failure_probability_upper": "1/100",
             "primitive_refs": [f"task:{task}"]},
        ],
        "lemmas": [], "uses": ["step", "arrival"], "conclusion": "(>= after 1)",
        "horizon_ms": 100, "metadata": {},
    }


def _contract(*rows: dict[str, Any]) -> Contract:
    tasks = []
    for name in ("advance", "publish"):
        tasks.append(Task(
            name, "worker", "Request", "Done", implementation=Implementation("python", "work.py", name),
            outcomes=(TaskOutcome("Done"),),
            source_signature=SourceSignature(
                "python", "work.py", name, "Request", ("Done",), 1,
                (("value", "int"),), (("Done", (("value", "int"),)),),
            ),
        ))
    return Contract(
        "dagcert-contract/v12", (Worker("worker", 1),), tuple(tasks), (),
        state_claims=tuple(StateClaim(row["id"], "lra_theorem", parse_theorem_spec(row)) for row in rows),
    )


def _parent(identifier: str, children: list[tuple[dict[str, Any], str, str]]) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    premises = []
    conclusions = []
    for child, prefix, invocation in children:
        substitutions = {}
        for name, variable in child["variables"].items():
            renamed = prefix + "_" + name
            substitutions[name] = renamed
            variables[renamed] = deepcopy(variable)
            variables[renamed]["binding"]["invocation"] = invocation
        premises.append({"id": prefix, "kind": "theorem", "claim": child["id"], "substitutions": substitutions})
        conclusions.append(f"(>= {prefix}_after 1)")
    return {
        "id": identifier, "kind": "lra_theorem", "mode": "source", "variables": variables,
        "premises": premises, "lemmas": [], "uses": [row["id"] for row in premises],
        "conclusion": f"(and {' '.join(conclusions)})", "horizon_ms": 100, "metadata": {},
    }


def test_imported_theorems_namespace_source_relations_by_their_defining_claim() -> None:
    first = _row("first")
    second = _row("second", task="publish")
    parent = _parent("combined", [(first, "a", "one"), (second, "b", "two")])
    contract = _contract(first, second, parent)
    proof = prove_theorem("combined", contract)
    assert len(proof.source_relations) == 2
    relations = contract_relations(contract)
    assert len({relation.id for relation in relations}) == len(relations)


def test_reusing_same_actual_invocation_does_not_double_charge_its_envelope() -> None:
    child = _row("child")
    parent = _parent("combined", [(child, "a", "same"), (child, "b", "same")])
    proof = prove_theorem("combined", _contract(child, parent))
    assert proof.failure_probability_upper == Fraction(1, 100)
    assert len(proof.events) == 1


def test_reusing_lemma_for_different_calls_keeps_both_failure_events() -> None:
    child = _row("child")
    parent = _parent("combined", [(child, "a", "first"), (child, "b", "second")])
    proof = prove_theorem("combined", _contract(child, parent))
    assert proof.failure_probability_upper == Fraction(1, 50)
    assert len(proof.events) == 2


def test_mathematical_lemma_hypothesis_does_not_become_a_physical_premise() -> None:
    math = {
        "id": "math", "kind": "lra_theorem", "mode": "mathematical",
        "variables": {"x": {"sort": "real", "unit": "item", "binding": None}},
        "premises": [{"id": "pretend", "kind": "fact", "formula": "(> x 100)"}],
        "lemmas": [], "uses": ["pretend"], "conclusion": "(> x 100)",
        "horizon_ms": None, "metadata": {},
    }
    source = _row("source")
    source["premises"].append({"id": "borrow", "kind": "theorem", "claim": "math", "substitutions": {"x": "after"}})
    source["uses"].append("borrow")
    source["conclusion"] = "(> after 100)"
    with pytest.raises(TheoremError, match="invalid"):
        prove_theorem("source", _contract(math, source))


def test_source_postcondition_does_not_prove_invocation_completion() -> None:
    row = _row("claim")
    row["premises"] = row["premises"][:1]
    row["uses"] = ["step"]
    row["conclusion"] = "done"
    with pytest.raises(TheoremError, match="invalid"):
        prove_theorem("claim", _contract(row))


def test_missing_completion_binding_is_rejected() -> None:
    row = _row("claim")
    del row["variables"]["done"]
    row["premises"] = row["premises"][:1]
    row["uses"] = ["step"]
    with pytest.raises(TheoremError, match="completed"):
        prove_theorem("claim", _contract(row))


def test_finite_horizon_theorem_cannot_be_imported_as_an_infinite_guarantee() -> None:
    child = _row("child")
    parent = _parent("combined", [(child, "a", "call")])
    parent["horizon_ms"] = None
    with pytest.raises(TheoremError, match="horizon"):
        prove_theorem("combined", _contract(child, parent))


def test_cross_theorem_cycle_is_not_an_inductive_proof() -> None:
    first = _row("first")
    second = _row("second")
    substitutions = {name: name for name in first["variables"]}
    for row, other in [(first, "second"), (second, "first")]:
        row["premises"].append({"id": "cycle", "kind": "theorem", "claim": other, "substitutions": substitutions})
        row["uses"].append("cycle")
    with pytest.raises(TheoremError, match="circular"):
        prove_theorem("first", _contract(first, second))


def test_local_lemma_cycle_is_not_an_inductive_proof() -> None:
    row = _row("claim")
    row["lemmas"] = [
        {"id": "a", "uses": ["b"], "conclusion": "(>= after 1)"},
        {"id": "b", "uses": ["a"], "conclusion": "(>= after 1)"},
    ]
    row["uses"] = ["a"]
    with pytest.raises(TheoremError, match="circular"):
        prove_theorem("claim", _contract(row))


def test_contradictory_reimported_source_hypotheses_cannot_prove_false() -> None:
    first = _row("first")
    second = _row("second")
    first["premises"][1]["formula"] = "(and done (= before 0))"
    second["premises"][1]["formula"] = "(and done (= before 1))"
    parent = _parent("combined", [(first, "a", "same"), (second, "b", "same")])
    parent["conclusion"] = "false"
    with pytest.raises(TheoremError, match="inconsistent"):
        prove_theorem("combined", _contract(first, second, parent))


def test_assume_conclusion_plus_irrelevant_source_fact_is_not_source_derived() -> None:
    row = _row("claim")
    row["premises"][0]["predicate"] = "True"
    row["premises"][1]["formula"] = row["conclusion"]
    with pytest.raises(TheoremError):
        prove_theorem("claim", _contract(row))


def _multi_outcome_row(identifier: str) -> dict[str, Any]:
    row = _row(identifier)
    row["variables"]["succeeded"] = _variable("advance", "$selected")
    row["variables"]["failed"] = _variable("advance", "$selected", outcome="Failed")
    row["premises"][1]["formula"] = "(and done succeeded (>= before 0))"
    return row


def _multi_outcome_contract(*rows: dict[str, Any]) -> Contract:
    contract = _contract(*rows)
    task = contract.task_by_id["advance"]
    signature = task.source_signature
    assert signature is not None
    task = replace(task, output_type="Done | Failed", outcomes=(TaskOutcome("Done"), TaskOutcome("Failed")),
                   source_signature=replace(signature, outcome_types=("Done", "Failed"),
                                            outcome_fields=(*signature.outcome_fields, ("Failed", (("value", "int"),)))))
    return replace(contract, tasks=(task, contract.task_by_id["publish"]))


@pytest.mark.parametrize("alias", ["before", "done"])
def test_invocation_owned_projection_alias_can_use_another_outcome_label(alias: str) -> None:
    child = _multi_outcome_row("child")
    parent = _parent("combined", [(child, "a", "call")])
    parent["variables"]["a_" + alias]["binding"]["outcome"] = "Failed"
    proof = prove_theorem("combined", _multi_outcome_contract(child, parent))
    assert proof.failure_probability_upper == Fraction(1, 100)


def test_same_input_envelope_is_not_double_charged_by_outcome_alias_labels() -> None:
    first = _multi_outcome_row("first")
    second = _multi_outcome_row("second")
    second["variables"]["before"]["binding"]["outcome"] = "Failed"
    second["variables"]["done"]["binding"]["outcome"] = "Failed"
    parent = _parent("combined", [(first, "a", "same"), (second, "b", "same")])
    proof = prove_theorem("combined", _multi_outcome_contract(first, second, parent))
    assert proof.failure_probability_upper == Fraction(1, 100)
    assert len(proof.events) == 1
