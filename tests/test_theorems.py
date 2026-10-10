"""General proof composition must not drop source hypotheses or failure events."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path

import pytest

from dagcert.contract import Contract, Implementation, StateClaim, Task, TaskOutcome, Worker, load_contract
from dagcert.certificate import CertificateError, issue_certificate, verify_certificate
from dagcert.source_types import SourceSignature
from dagcert.theorems import TheoremError, parse_theorem_spec, prove_theorem


def _variable(field, sort="real", invocation="one"):
    return {"sort": sort, "unit": "boolean" if sort == "bool" else "count", "binding": {
        "task": "work", "invocation": invocation, "outcome": "WorkCompleted", "field": field,
    }}


def _source_spec(identifier="increment", probability="1/100"):
    return {
        "id": identifier, "kind": "lra_theorem", "mode": "source",
        "variables": {"x": _variable("input.value"), "y": _variable("result.value"),
                      "done": _variable("$completed", "bool")},
        "premises": [
            {"id": "implementation", "kind": "source", "task": "work", "invocation": "one",
             "outcome": "WorkCompleted", "predicate": "result.value == input.value + 1"},
            {"id": "completion", "kind": "envelope", "formula": "done",
             "assumption": "This invocation completes in the declared observation window.",
             "event": "work-completion", "horizon_ms": 100, "failure_probability_upper": probability,
             "primitive_refs": ["task:work"]},
        ],
        "lemmas": [{"id": "difference", "uses": ["implementation", "completion"], "conclusion": "(= (- y x) 1)"}],
        "uses": ["difference"], "conclusion": "(> y x)", "horizon_ms": 100, "metadata": {},
    }


def _contract(*rows):
    signature = SourceSignature("python", "app.py", "work", "WorkInput", ("WorkCompleted",), 1,
                                (("value", "int"),), (("WorkCompleted", (("value", "int"),)),))
    task = Task("work", "worker", "WorkInput", "WorkCompleted",
                implementation=Implementation("python", "app.py", "work"),
                source_signature=signature, outcomes=(TaskOutcome("WorkCompleted"),))
    return Contract("dagcert-contract/v12", (Worker("worker", 1),), (task,), (),
                    state_claims=tuple(StateClaim(row["id"], "lra_theorem", parse_theorem_spec(row)) for row in rows))


def test_source_theorem_and_local_lemma_are_checked_not_asserted():
    contract = _contract(_source_spec())
    result = prove_theorem("increment", contract)
    assert result.failure_probability_upper == Fraction(1, 100)
    assert len(result.source_relations) == 1
    bad = _source_spec()
    bad["conclusion"] = "(> y (+ x 1))"
    with pytest.raises(TheoremError, match="invalid.*counterexample"):
        prove_theorem("increment", _contract(bad))


def test_postcondition_never_establishes_invocation_completion():
    row = _source_spec()
    row["premises"] = row["premises"][:1]
    row["lemmas"] = []
    row["uses"] = ["implementation"]
    row["conclusion"] = "done"
    with pytest.raises(TheoremError, match="invalid"):
        prove_theorem("increment", _contract(row))


def test_conditional_mathematical_lemma_cannot_launder_its_hypotheses():
    math = {
        "id": "positive", "kind": "lra_theorem", "mode": "mathematical",
        "variables": {"a": {"sort": "real", "unit": "count", "binding": None}},
        "premises": [{"id": "nonnegative", "kind": "fact", "formula": "(>= a 0)"}],
        "lemmas": [], "uses": ["nonnegative"], "conclusion": "(>= (+ a 1) 1)",
        "horizon_ms": None, "metadata": {},
    }
    row = _source_spec()
    row["premises"].append({"id": "generic", "kind": "theorem", "claim": "positive", "substitutions": {"a": "x"}})
    row["uses"] = ["difference", "generic"]
    row["conclusion"] = "(>= y 1)"
    with pytest.raises(TheoremError, match="invalid"):
        prove_theorem("increment", _contract(math, row))
    row["premises"][1]["formula"] = "(and done (>= x 0))"
    assert prove_theorem("increment", _contract(math, row)).source_relations


def _importing_child(child_id, identifier, invocation="one"):
    row = _source_spec(identifier)
    row["variables"] = {name: {**descriptor, "binding": {**descriptor["binding"], "invocation": invocation}}
                        for name, descriptor in row["variables"].items()}
    row["premises"] = [{"id": "child", "kind": "theorem", "claim": child_id,
                        "substitutions": {"x": "x", "y": "y", "done": "done"}}]
    row["lemmas"] = []
    row["uses"] = ["child"]
    return row


def test_diamond_reuses_one_envelope_event_but_distinct_invocations_do_not():
    root = _source_spec("root")
    left = _importing_child("root", "left")
    right = _importing_child("root", "right")
    final = _importing_child("left", "final")
    final["premises"].append({"id": "right", "kind": "theorem", "claim": "right",
                              "substitutions": {"x": "x", "y": "y", "done": "done"}})
    final["uses"].append("right")
    assert prove_theorem("final", _contract(root, left, right, final)).failure_probability_upper == Fraction(1, 100)
    for name, field in (("x2", "input.value"), ("y2", "result.value"), ("done2", "$completed")):
        final["variables"][name] = _variable(field, "bool" if name == "done2" else "real", "two")
    final["premises"][-1]["substitutions"] = {"x": "x2", "y": "y2", "done": "done2"}
    assert prove_theorem("final", _contract(root, left, right, final)).failure_probability_upper == Fraction(1, 50)


def test_import_preserves_horizon_and_source_projection():
    root, child = _source_spec("root"), _importing_child("root", "child")
    child["horizon_ms"] = None
    with pytest.raises(TheoremError, match="horizon"):
        prove_theorem("child", _contract(root, child))
    child["horizon_ms"] = 100
    child["premises"][0]["substitutions"]["x"] = "y"
    with pytest.raises(TheoremError, match="relabeled"):
        prove_theorem("child", _contract(root, child))


def test_circular_claims_and_local_lemmas_refuse():
    first, second = _importing_child("second", "first"), _importing_child("first", "second")
    with pytest.raises(TheoremError, match="circular"):
        prove_theorem("first", _contract(first, second))
    row = _source_spec()
    row["lemmas"] = [{"id": "cycle", "uses": ["cycle"], "conclusion": "true"}]
    row["uses"] = ["cycle"]
    with pytest.raises(TheoremError, match="circular"):
        prove_theorem("increment", _contract(row))


def _install(project, wrong_source=False):
    path = Path(str(project["contract"]))
    document = json.loads(path.read_text())
    document["schema"] = "dagcert-contract/v7"
    for task in document["tasks"]:
        task["start_resources"] = {}
    row = _source_spec()
    if wrong_source:
        row["premises"][0]["predicate"] = "result.value == input.value + 2"
        row["lemmas"][0]["conclusion"] = "(= (- y x) 2)"
    document["state_claims"] = [row]
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    requirements_path = Path(str(project["requirements"]))
    requirements = json.loads(requirements_path.read_text())
    requirements["claims"].append({
        "id": "increment-theorem", "statement": "Under the disclosed completion envelope, the real operation increases its input.",
        "basis": "chance", "primitive_refs": ["task:work", "state-claim:increment"], "checker_refs": [],
        "assumptions": ["The invocation completion envelope holds over the declared 100ms window with failure probability at most 1/100."],
        "formula": {"gte": [{"state_claim_success_probability_lower": "state-claim:increment"}, 0.99]},
    })
    requirements_path.write_text(json.dumps(requirements, indent=2), encoding="utf-8")


def test_source_theorem_certificate_issues_and_independently_rechecks(project):
    _install(project)
    root = Path(str(project["root"]))
    certificate_path = root / "artifacts/theorem.json"
    certificate = issue_certificate(project["contract"], project["evidence"], certificate_path,
                                    requirements_path=project["requirements"], source_root=root)
    assert certificate["source_verification"]["relations"]["status"] == "proved"
    result = verify_certificate(certificate_path, contract_path=project["contract"],
                                evidence_path=project["evidence"], requirements_path=project["requirements"], source_root=root)
    assert result.valid, result.problems


def test_true_arithmetic_about_false_source_relation_cannot_issue(project):
    _install(project, wrong_source=True)
    root = Path(str(project["root"]))
    with pytest.raises(CertificateError, match="source relational proof refused"):
        issue_certificate(project["contract"], project["evidence"], root / "artifacts/theorem.json",
                          requirements_path=project["requirements"], source_root=root)
