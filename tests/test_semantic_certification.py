"""Certificate gates must prove the declared recurrence against actual source."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from dagcert.certificate import CertificateError, issue_certificate, verify_certificate
from dagcert.certificate import canonical_json
from dagcert.contract import load_contract
from dagcert.induction import prove_inductive_invariant
from dagcert.semantic import contract_relations


def _install_recurrence(project: dict[str, object], increment: int) -> None:
    path = Path(str(project["contract"]))
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema"] = "dagcert-contract/v7"
    for task in document["tasks"]:
        task["start_resources"] = {}
    document["state_claims"] = [{
        "id": "nonnegative", "kind": "relational_invariant",
        "variables": {"value": "int"}, "initial": "state.value == 0",
        "invariant": "state.value >= 0",
        "transitions": [{
            "task": "work", "outcome": "WorkCompleted",
            "before": {"value": "input.value"}, "after": {"value": "result.value"},
            "relation": f"after.value == before.value + {increment}",
        }],
        "assumption": "Initial value is zero; only work mutates this state; each returned value feeds the next request atomically.",
        "metadata": {},
    }]
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def test_true_induction_with_false_source_transition_cannot_be_certified(project: dict[str, object]) -> None:
    _install_recurrence(project, 2)
    root = Path(str(project["root"]))
    contract = load_contract(Path(str(project["contract"])), source_root=root)
    # Both increments preserve nonnegativity. Only +1 is implemented by the real function.
    assert prove_inductive_invariant(contract.state_claims[0].specification, contract)[0]
    assert contract_relations(contract)
    with pytest.raises(CertificateError, match="source relational proof refused"):
        issue_certificate(
            Path(str(project["contract"])), Path(str(project["evidence"])), root / "artifacts/certificate.json",
            requirements_path=Path(str(project["requirements"])), source_root=root,
        )


def test_relations_are_sealed_and_independently_rechecked(project: dict[str, object]) -> None:
    _install_recurrence(project, 1)
    root = Path(str(project["root"]))
    certificate_path = root / "artifacts/certificate.json"
    document = issue_certificate(
        Path(str(project["contract"])), Path(str(project["evidence"])), certificate_path,
        requirements_path=Path(str(project["requirements"])), source_root=root,
    )
    assert document["source_verification"]["relations"]["status"] == "proved"
    tampered = deepcopy(document)
    tampered["source_verification"]["relations"]["relations"][0]["predicate"] = "True"
    certificate_path.write_text(json.dumps(tampered), encoding="utf-8")
    result = verify_certificate(
        certificate_path, contract_path=Path(str(project["contract"])),
        evidence_path=Path(str(project["evidence"])), requirements_path=Path(str(project["requirements"])),
        source_root=root,
    )
    assert not result.valid
    assert any("source verification" in problem for problem in result.problems)


def test_legacy_certificate_label_cannot_downgrade_source_proof(project: dict[str, object]) -> None:
    _install_recurrence(project, 1)
    root = Path(str(project["root"]))
    certificate_path = root / "artifacts/certificate.json"
    document = issue_certificate(
        Path(str(project["contract"])), Path(str(project["evidence"])), certificate_path,
        requirements_path=Path(str(project["requirements"])), source_root=root,
    )
    document["schema"] = "dagcert-certificate/v4"
    for name in ("claim_analysis", "source_verification", "type_enforcement", "certificate_sha256"):
        document.pop(name)
    document["certificate_sha256"] = sha256(canonical_json(document)).hexdigest()
    certificate_path.write_text(json.dumps(document), encoding="utf-8")
    result = verify_certificate(
        certificate_path, contract_path=Path(str(project["contract"])),
        evidence_path=Path(str(project["evidence"])), requirements_path=Path(str(project["requirements"])),
        source_root=root,
    )
    assert not result.valid
    assert any("cannot verify a source-typed contract" in problem for problem in result.problems)
