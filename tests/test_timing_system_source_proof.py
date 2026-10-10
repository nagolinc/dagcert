"""Actual pinned semantic-backend acceptance, without mocked proof results."""

import pytest

from dagcert.certificate import source_fingerprint
from dagcert.relations import RelationError, SourceRelation, verify_source_relations
from examples.timing_systems.invariants import (
    SOURCE_ROOT,
    source_contract,
    source_obligations,
)


def test_real_nagini_proves_all_five_system_policy_and_induction_relations() -> None:
    contract = source_contract()
    relations = source_obligations(contract)
    original = (SOURCE_ROOT / "operations.py").read_bytes()
    proof = verify_source_relations(
        contract, SOURCE_ROOT, relations, None, source_fingerprint(SOURCE_ROOT),
        source_manifest_paths=["operations.py"],
    )
    assert proof["status"] == "proved"
    assert proof["original_sources"] != proof["proof_sources"]
    assert len(proof["relations"]) == len(relations)  # type: ignore[arg-type]
    assert (SOURCE_ROOT / "operations.py").read_bytes() == original
    verification = proof["verification"]
    assert isinstance(verification, dict)
    verifier = verification["exception_verifier"]
    assert verifier["checker"] == "nagini"
    assert len(verifier["launcher_sha256"]) == 64
    assert any(row["union_generator_arity"] >= 6 for row in verifier["files"])


def test_real_nagini_refuses_an_incorrect_claim_about_an_actual_accepted_segment() -> None:
    false_relation = SourceRelation(
        "incorrect-av-prefix", "av.join", "AVJoined",
        "result.next_sequence == input.next_sequence",
    )
    with pytest.raises(RelationError, match="Verification failed"):
        verify_source_relations(
            source_contract(), SOURCE_ROOT, [false_relation], None, source_fingerprint(SOURCE_ROOT),
            source_manifest_paths=["operations.py"],
        )
