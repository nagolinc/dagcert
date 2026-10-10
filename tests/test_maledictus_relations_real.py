"""Real executable controls for the Dagcert/Maledictus semantic adapter.

Set both DAGCERT_MALEDICTUS_EXECUTABLE and DAGCERT_MALEDICTUS_SHA256 to run.
Protocol doubles elsewhere cannot substitute for these implementation checks.
"""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path

import pytest

from dagcert.contract import load_contract
from dagcert.relations import RelationError, SourceRelation, verify_source_relations
from dagcert.source_types import SourceProofBackend


@pytest.fixture
def real_maledictus() -> SourceProofBackend:
    executable = os.environ.get("DAGCERT_MALEDICTUS_EXECUTABLE")
    digest = os.environ.get("DAGCERT_MALEDICTUS_SHA256")
    if executable is None and digest is None:
        pytest.skip("real Maledictus integration requires an executable and its SHA-256 pin")
    assert executable is not None and digest is not None, "set both real-backend environment variables"
    assert sha256(Path(executable).read_bytes()).hexdigest() == digest
    return SourceProofBackend.maledictus(executable, digest)


def _prove(project: dict[str, object], backend: SourceProofBackend, predicate: str) -> dict[str, object]:
    root = Path(str(project["root"]))
    contract = load_contract(Path(str(project["contract"])), source_root=root)
    return verify_source_relations(
        contract, root, [SourceRelation("increment", "work", "WorkCompleted", predicate)],
        backend, str(project["fingerprint"]), source_manifest_paths=["app.py"],
    )


def test_real_record_increment_semantic_relation(project: dict[str, object], real_maledictus: SourceProofBackend) -> None:
    result = _prove(project, real_maledictus, "result.value == input.value + 1")
    assert result["status"] == "proved"
    assert result["original_sources"] != result["proof_sources"]


def test_real_record_false_increment_refused(project: dict[str, object], real_maledictus: SourceProofBackend) -> None:
    with pytest.raises(RelationError, match="source relational proof refused") as failure:
        _prove(project, real_maledictus, "result.value == input.value + 2")
    diagnostic = str(failure.value)
    assert "postcondition.violated:assertion.false" in diagnostic, diagnostic
    assert "frontend." not in diagnostic, "A frontend refusal is not a semantic refutation"
    assert "insufficient.permission" not in diagnostic, "A missing read permission is not a false value relation"
