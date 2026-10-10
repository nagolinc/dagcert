"""Finite nominal source paths, not guessed types or flattened record names."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
from typing import Any

import pytest

from dagcert.certificate import _serialized_primitives, source_fingerprint
from dagcert.contract import Contract, Implementation, Task, TaskOutcome, Worker
from dagcert.linear_logic import prove_implication
from dagcert.relations import RelationError, verify_source_relations
from dagcert.source_types import SourceProofBackend, SourceSignature, read_python_signature
from dagcert.theorem_sources import TheoremSourceError, source_binding_constraints, source_fact


def _write(root: Path, path: str, source: str) -> None:
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8")


def _project(root: Path, *, turn_field: str = "id: int", frozen: bool = True) -> SourceSignature:
    _write(root, "records/__init__.py", "")
    _write(root, "records/model.py", (
        "from dataclasses import dataclass\n\n"
        f"@dataclass(frozen={frozen})\nclass Turn:\n    {turn_field}\n"
    ))
    # Source aliases and relative imports must retain model.py:Turn identity.
    _write(root, "records/exports.py", "from .model import Turn as ExportedTurn\n\n__all__ = ['ExportedTurn']\n")
    _write(root, "records/narration.py", (
        "from dataclasses import dataclass\nfrom .exports import ExportedTurn as ActualTurn\n\n"
        "@dataclass(frozen=True)\nclass Narration:\n    turn: ActualTurn\n"
    ))
    _write(root, "records/outcomes.py", (
        "from dataclasses import dataclass\nimport records.model as models\n\n"
        "@dataclass(frozen=True)\nclass Published:\n    turn_id: int\n    receipt: models.Turn\n\n"
        "@dataclass(frozen=True)\nclass Failed:\n    error: int\n"
    ))
    _write(root, "operations.py", (
        "from dataclasses import dataclass\nfrom dagcert.runtime import operation\n"
        "from records.narration import Narration\nfrom records.outcomes import Published, Failed\n\n"
        "@dataclass(frozen=True)\nclass Request:\n    narration: Narration\n\n"
        "@operation\ndef work(request: Request) -> Published | Failed:\n"
        "    return Published(request.narration.turn.id, request.narration.turn)\n"
    ))
    return read_python_signature(root, "operations.py", "work")


def _contract(signature: SourceSignature) -> Contract:
    task = Task(
        "work", "worker", signature.input_type, " | ".join(signature.outcome_types),
        implementation=Implementation("python", "operations.py", "work"),
        outcomes=tuple(TaskOutcome(outcome) for outcome in signature.outcome_types),
        source_signature=signature,
    )
    return Contract("dagcert-contract/v12", (Worker("worker", 1),), (task,), ())


def _variable(field: str, *, outcome: str = "Published", sort: str = "real", unit: str = "turn-id") -> dict[str, Any]:
    return {"sort": sort, "unit": unit, "binding": {
        "task": "work", "invocation": "one", "outcome": outcome, "field": field,
    }}


def _variables() -> dict[str, Any]:
    return {
        "before": _variable("input.narration.turn.id"),
        "after": _variable("result.turn_id"),
        "receipt": _variable("result.receipt.id"),
        "done": _variable("$completed", sort="bool", unit="boolean"),
        "published": _variable("$selected", sort="bool", unit="boolean"),
        "failed": _variable("$selected", outcome="Failed", sort="bool", unit="boolean"),
    }


def _premise(predicate: str) -> dict[str, str]:
    return {"id": "copy", "kind": "source", "task": "work", "invocation": "one",
            "outcome": "Published", "predicate": predicate}


def _prove(variables: dict[str, Any], assumptions: list[str], conclusion: str) -> str:
    return prove_implication({name: row["sort"] for name, row in variables.items()}, assumptions, conclusion).status


def test_actual_imported_nested_records_keep_nominal_paths_and_original_predicate(tmp_path: Path) -> None:
    signature = _project(tmp_path)
    records = {record.identity: record for record in signature.projection_records}
    assert set(records) == {
        "operations.py:Request", "records/narration.py:Narration", "records/model.py:Turn",
        "records/outcomes.py:Published", "records/outcomes.py:Failed",
    }
    assert records["records/narration.py:Narration"].fields[0].record == "records/model.py:Turn"
    assert dict(signature.input_fields) == {"narration": "Narration"}
    assert dict(dict(signature.outcome_fields)["Published"])["receipt"] == "models.Turn"
    contract, variables = _contract(signature), _variables()
    predicate = "result.turn_id == input.narration.turn.id and result.receipt.id == input.narration.turn.id"
    formula, relation = source_fact(_premise(predicate), variables, contract)
    assert relation.predicate == predicate
    assumptions = source_binding_constraints(variables, contract) + [formula]
    assert _prove(variables, assumptions + ["published"], "(and (= after before) (= receipt before))") == "valid"
    assert _prove(variables, assumptions, "(= after before)") == "invalid"
    assert _prove(variables, assumptions + ["failed"], "(= after before)") == "invalid"


def test_nested_aliases_share_input_identity_across_outcomes_and_preserve_units(tmp_path: Path) -> None:
    contract, variables = _contract(_project(tmp_path)), _variables()
    variables["same_input"] = _variable("input.narration.turn.id", outcome="Failed")
    variables["same_result"] = _variable("result.receipt.id")
    constraints = source_binding_constraints(variables, contract)
    assert _prove(variables, constraints, "(and (= before same_input) (= receipt same_result))") == "valid"
    variables["same_input"]["unit"] = "seconds"
    with pytest.raises(TheoremSourceError, match="units"):
        source_binding_constraints(variables, contract)


@pytest.mark.parametrize("field", [
    "input.narration.missing.id", "input.narration.turn.id.real", "input.narration.turn.__class__",
    "input.narration.turn[id]", "input.narration..id",
])
def test_nested_paths_do_not_invent_fields_or_allow_mapping_and_dunder_tricks(tmp_path: Path, field: str) -> None:
    contract, variables = _contract(_project(tmp_path)), _variables()
    variables["bad"] = _variable(field)
    with pytest.raises(TheoremSourceError):
        source_binding_constraints(variables, contract)


def test_outcome_specific_nested_fields_cannot_be_borrowed_by_failure(tmp_path: Path) -> None:
    contract, variables = _contract(_project(tmp_path)), _variables()
    variables["bad"] = _variable("result.receipt.id", outcome="Failed")
    with pytest.raises(TheoremSourceError, match="no compiler-extracted"):
        source_binding_constraints(variables, contract)


@pytest.mark.parametrize("annotation", ["float", "bool", "str", "int | None", "list[int]"])
def test_nested_leaf_does_not_erase_float_bool_optional_or_container_types(tmp_path: Path, annotation: str) -> None:
    contract, variables = _contract(_project(tmp_path, turn_field=f"id: {annotation}")), _variables()
    with pytest.raises(TheoremSourceError, match="int or bool|requires theorem sort"):
        source_binding_constraints(variables, contract)


def test_nested_boolean_leaf_retains_boolean_sort(tmp_path: Path) -> None:
    contract, variables = _contract(_project(tmp_path, turn_field="id: bool")), _variables()
    for name in ("before", "receipt"):
        variables[name]["sort"] = "bool"
        variables[name]["unit"] = "boolean"
    formula, relation = source_fact(_premise("input.narration.turn.id is result.receipt.id"), variables, contract)
    assert relation.predicate == "input.narration.turn.id is result.receipt.id"
    assert _prove(variables, source_binding_constraints(variables, contract) + [formula, "published"], "(= before receipt)") == "valid"


def test_mutable_record_hop_is_not_an_immutable_source_projection(tmp_path: Path) -> None:
    with pytest.raises(TheoremSourceError, match="frozen"):
        source_binding_constraints(_variables(), _contract(_project(tmp_path, frozen=False)))


def test_optional_record_hop_is_not_assumed_present(tmp_path: Path) -> None:
    _project(tmp_path)
    path = tmp_path / "records/narration.py"
    path.write_text(path.read_text().replace("turn: ActualTurn", "turn: ActualTurn | None"), encoding="utf-8")
    signature = read_python_signature(tmp_path, "operations.py", "work")
    with pytest.raises(TheoremSourceError, match="optional, union"):
        source_binding_constraints(_variables(), _contract(signature))


def test_same_named_records_in_different_modules_do_not_erase_scalar_types(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path, "records/other.py", (
        "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass Turn:\n    id: bool\n"
    ))
    path = tmp_path / "records/narration.py"
    text = path.read_text().replace("from dataclasses import dataclass", "from dataclasses import dataclass\nimport records.other as other")
    path.write_text(text.replace("turn: ActualTurn", "turn: ActualTurn\n    second: other.Turn"), encoding="utf-8")
    signature = read_python_signature(tmp_path, "operations.py", "work")
    assert {record.identity for record in signature.projection_records if record.symbol == "Turn"} == {
        "records/model.py:Turn", "records/other.py:Turn",
    }
    variables = _variables()
    variables["other"] = _variable("input.narration.second.id")
    with pytest.raises(TheoremSourceError, match="requires theorem sort bool"):
        source_binding_constraints(variables, _contract(signature))
    variables["other"]["sort"] = "bool"
    assert source_binding_constraints(variables, _contract(signature))


def test_reimported_dataclass_decorator_cannot_supply_a_frozen_projection(tmp_path: Path) -> None:
    _project(tmp_path)
    path = tmp_path / "records/model.py"
    path.write_text(path.read_text().replace("from dataclasses import dataclass", "from dataclasses import dataclass\nfrom invented import dataclass"), encoding="utf-8")
    signature = read_python_signature(tmp_path, "operations.py", "work")
    with pytest.raises(TheoremSourceError, match="frozen"):
        source_binding_constraints(_variables(), _contract(signature))


@pytest.mark.parametrize("prefix", [
    "from invented import *\n",
    "if True:\n    from invented import dataclass\n",
    "try:\n    int = bool\nexcept Exception:\n    pass\n",
    "for int in []:\n    pass\n",
])
def test_wildcard_and_conditional_bindings_cannot_guess_nested_scalar_provenance(tmp_path: Path, prefix: str) -> None:
    _project(tmp_path)
    path = tmp_path / "records/model.py"
    path.write_text(path.read_text().replace("from dataclasses import dataclass\n", "from dataclasses import dataclass\n" + prefix), encoding="utf-8")
    signature = read_python_signature(tmp_path, "operations.py", "work")
    with pytest.raises(TheoremSourceError):
        source_binding_constraints(_variables(), _contract(signature))


@pytest.mark.parametrize("mutation", [
    "from invented import *\n",
    "if True:\n    Request = Published\n    Published = Failed\n",
])
def test_ambiguous_extracted_root_never_falls_back_to_legacy_flat_fields(tmp_path: Path, mutation: str) -> None:
    _project(tmp_path)
    path = tmp_path / "operations.py"
    path.write_text(path.read_text() + mutation, encoding="utf-8")
    signature = read_python_signature(tmp_path, "operations.py", "work")
    assert dict(signature.projection_roots)["input"] is None
    variables = _variables()
    with pytest.raises(TheoremSourceError, match="no source-owned record projection"):
        source_binding_constraints(variables, _contract(signature))
    # Even the legacy top-level Published.turn_id may not rescue ambiguity.
    variables = {name: row for name, row in variables.items() if name in {"after", "done", "published", "failed"}}
    with pytest.raises(TheoremSourceError, match="no source-owned record projection"):
        source_binding_constraints(variables, _contract(signature))


def test_recursive_schema_is_finite_and_has_no_arbitrary_projection_depth_limit(tmp_path: Path) -> None:
    _write(tmp_path, "operations.py", (
        "from dataclasses import dataclass\nfrom dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\nclass Node:\n    next: 'Node'\n    value: int\n\n"
        "@dataclass(frozen=True)\nclass Completed:\n    value: int\n\n"
        "@operation\ndef work(request: Node) -> Completed:\n    return Completed(request.value)\n"
    ))
    signature = read_python_signature(tmp_path, "operations.py", "work")
    assert len(signature.projection_records) == 2
    node = next(record for record in signature.projection_records if record.symbol == "Node")
    assert node.fields[0].record == node.identity
    variables = {
        "deep": _variable("input." + "next." * 150 + "value", outcome="Completed"),
        "done": _variable("$completed", outcome="Completed", sort="bool", unit="boolean"),
    }
    assert source_binding_constraints(variables, _contract(signature)) == []
    # Schema traversal is not a proof that this operation follows that path or
    # that arbitrary cyclic objects satisfy a postcondition.


def test_unresolved_source_reexport_cycle_does_not_loop_or_invent_a_record(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path, "records/exports.py", "from .cycle import ExportedTurn\n")
    _write(tmp_path, "records/cycle.py", "from .exports import ExportedTurn\n")
    signature = read_python_signature(tmp_path, "operations.py", "work")
    with pytest.raises(TheoremSourceError, match="resolved direct source-record edge"):
        source_binding_constraints(_variables(), _contract(signature))


def test_source_record_graph_is_sealed_but_old_or_empty_signatures_keep_old_shape(tmp_path: Path) -> None:
    signature = _project(tmp_path)
    contract = _contract(signature)
    document = _serialized_primitives(contract, {"timings": []})
    sealed = document["tasks"][0]["source_signature"]
    assert sealed["projection_roots"] and sealed["projection_records"]
    records = list(signature.projection_records)
    index = next(i for i, record in enumerate(records) if record.symbol == "Turn")
    fields = records[index].fields
    records[index] = replace(records[index], fields=(replace(fields[0], annotation="float", scalar="float"),))
    changed = _contract(replace(signature, projection_records=tuple(records)))
    assert _serialized_primitives(changed, {"timings": []}) != document
    for compatible in (
        replace(contract, schema="dagcert-contract/v11"),
        _contract(replace(signature, projection_roots=(), projection_records=())),
    ):
        old_signature = _serialized_primitives(compatible, {"timings": []})["tasks"][0]["source_signature"]
        assert "projection_roots" not in old_signature and "projection_records" not in old_signature


@pytest.mark.parametrize("delta", [0, 1])
def test_real_backend_checks_original_nested_relation(tmp_path: Path, delta: int) -> None:
    executable = os.environ.get("DAGCERT_MALEDICTUS_EXECUTABLE")
    digest = os.environ.get("DAGCERT_MALEDICTUS_SHA256")
    if executable is None and digest is None:
        pytest.skip("Set the explicit real Maledictus executable and hash to run source semantics")
    assert executable and digest, "Set both the real Maledictus executable and its SHA-256 pin"
    assert sha256(Path(executable).read_bytes()).hexdigest() == digest
    # Keep this semantic gate independent of backend import-alias support.
    # Imported/aliased source schema extraction is exercised separately above.
    _write(tmp_path, "operations.py", (
        "from dataclasses import dataclass\nfrom dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\nclass Turn:\n    id: int\n\n"
        "@dataclass(frozen=True)\nclass Narration:\n    turn: Turn\n\n"
        "@dataclass(frozen=True)\nclass Request:\n    narration: Narration\n\n"
        "@dataclass(frozen=True)\nclass Published:\n    turn_id: int\n    receipt: Turn\n\n"
        "@dataclass(frozen=True)\nclass Failed:\n    error: int\n\n"
        "@operation\ndef work(request: Request) -> Published | Failed:\n"
        "    return Published(request.narration.turn.id, request.narration.turn)\n"
    ))
    contract = _contract(read_python_signature(tmp_path, "operations.py", "work"))
    variables = _variables()
    predicate = f"result.turn_id == input.narration.turn.id + {delta}"
    _, relation = source_fact(_premise(predicate), variables, contract)
    backend = SourceProofBackend.maledictus(executable, digest)
    if delta == 0:
        proof = verify_source_relations(contract, tmp_path, [relation], backend, source_fingerprint(tmp_path))
        assert proof["status"] == "proved"
    else:
        with pytest.raises(RelationError, match="source relational proof refused") as failure:
            verify_source_relations(contract, tmp_path, [relation], backend, source_fingerprint(tmp_path))
        diagnostic = str(failure.value)
        assert "postcondition.violated:assertion.false" in diagnostic, diagnostic
        assert "frontend." not in diagnostic, "A frontend refusal is not a semantic refutation"
        assert "insufficient.permission" not in diagnostic, "A missing read permission is not a false value relation"
