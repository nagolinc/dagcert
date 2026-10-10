"""Actual release policy semantics, generic LRA timing, and real source issuance."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from dagcert.certificate import CertificateError, issue_certificate, verify_certificate
from dagcert.contract import ContractError, load_contract
from dagcert.theorems import prove_theorem
from examples.timing_logic.model import (
    ENVELOPE_ID, SOURCE_ROOT, THEOREM_ID, contract_document, requirements_document,
)
from examples.timing_logic.operations import ReleaseRequest, decide_release


def _request() -> ReleaseRequest:
    return ReleaseRequest(
        expected_version=7, now_ms=15,
        a_present=True, a_replica=1, a_version=7, a_arrived_ms=10,
        b_present=True, b_replica=2, b_version=7, b_arrived_ms=12,
        c_present=False, c_replica=3, c_version=7, c_arrived_ms=0,
    )


def _files(tmp_path: Path, document: dict[str, Any] | None = None) -> tuple[Path, Path, Path, Path]:
    document = document or contract_document()
    contract = tmp_path / "dag_contract.json"
    requirements = tmp_path / "english_requirements.json"
    evidence = tmp_path / "timings.jsonl"
    certificate = tmp_path / "certificate.json"
    contract.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    requirements.write_text(json.dumps(requirements_document(document), indent=2) + "\n", encoding="utf-8")
    evidence.write_text("", encoding="utf-8")
    return contract, requirements, evidence, certificate


def test_policy_releases_after_any_distinct_pair_without_waiting_for_missing_third() -> None:
    request = _request()
    assert decide_release(request).released
    assert decide_release(request).release_ms == 15
    assert decide_release(replace(request, a_present=False, c_present=True)).released
    assert decide_release(replace(request, b_present=False, c_present=True)).released


@pytest.mark.parametrize("change", [
    {"b_replica": 1}, {"b_version": 6}, {"b_present": False},
    {"b_arrived_ms": 20}, {"b_replica": -1}, {"b_arrived_ms": -1},
])
def test_duplicate_wrong_version_absent_or_not_arrived_ack_does_not_release(change: dict[str, Any]) -> None:
    decision = decide_release(replace(_request(), **change))
    assert not decision.released


def test_generic_lra_derives_nonzero_chance_bound_from_real_policy(tmp_path: Path) -> None:
    path, _, _, _ = _files(tmp_path)
    proof = prove_theorem(THEOREM_ID, load_contract(path, source_root=SOURCE_ROOT))
    assert str(proof.failure_probability_upper) == "1/1000"
    assert len(proof.source_relations) == 2


def test_source_quorum_readiness_without_bounded_dispatch_does_not_prove_deadline(tmp_path: Path) -> None:
    document = contract_document()
    envelope = next(item for item in document["state_claims"][0]["premises"] if item["id"] == ENVELOPE_ID)
    envelope["formula"] = "(and done (>= now_ms deadline))"
    path, _, _, _ = _files(tmp_path, document)
    with pytest.raises(ContractError, match="invalid"):
        prove_theorem(THEOREM_ID, load_contract(path, source_root=SOURCE_ROOT))


def test_real_source_certificate_issues_and_independently_verifies(tmp_path: Path) -> None:
    contract, requirements, evidence, certificate_path = _files(tmp_path)
    certificate = issue_certificate(
        contract, evidence, certificate_path, requirements_path=requirements, source_root=SOURCE_ROOT,
    )
    assert certificate["source_verification"]["relations"]["status"] == "proved"
    verified = verify_certificate(
        certificate_path, contract_path=contract, evidence_path=evidence,
        requirements_path=requirements, source_root=SOURCE_ROOT,
    )
    assert verified.valid, verified.problems


def test_arithmetic_cannot_replace_false_source_readiness_proof(tmp_path: Path) -> None:
    document = deepcopy(contract_document())
    document["state_claims"][0]["premises"][0]["predicate"] = "result.released"
    contract, requirements, evidence, certificate_path = _files(tmp_path, document)
    with pytest.raises(CertificateError, match="source relational proof refused"):
        issue_certificate(
            contract, evidence, certificate_path, requirements_path=requirements, source_root=SOURCE_ROOT,
        )
