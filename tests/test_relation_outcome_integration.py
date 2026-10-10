"""Real pinned-backend controls for relational facts on disjoint outcomes.

Run with DAGCERT_MALEDICTUS_EXECUTABLE and DAGCERT_MALEDICTUS_SHA256. A refused
frontend shape is not counted as semantic rejection of a deliberately false
predicate: the paired positive case must work and the negative must reach proof.
"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from dagcert import source_fingerprint
from dagcert.contract import load_contract
from dagcert.relations import RelationError, SourceRelation, build_relation_proof_view, verify_source_relations
from dagcert.source_types import SourceProofBackend


_SOURCE = '''from dataclasses import dataclass
from dagcert.runtime import operation

@dataclass(frozen=True)
class WorkInput:
    active: bool
    value: int

@dataclass(frozen=True)
class WorkCompleted:
    value: int

@dataclass(frozen=True)
class WorkIdle:
    reason: str

@dataclass(frozen=True)
class WorkRejected:
    value: int

@operation
def work(request: WorkInput) -> WorkCompleted | WorkIdle | WorkRejected:
    if not request.active:
        return WorkIdle("disabled")
    if request.value < 0:
        return WorkRejected(request.value)
    return WorkCompleted(request.value + 1)
'''


@pytest.fixture
def outcome_backend() -> SourceProofBackend:
    executable = os.environ.get("DAGCERT_MALEDICTUS_EXECUTABLE")
    digest = os.environ.get("DAGCERT_MALEDICTUS_SHA256")
    if executable is None and digest is None:
        pytest.skip("real outcome integration requires a pinned Maledictus executable")
    assert executable is not None and digest is not None, "set both backend environment variables"
    assert sha256(Path(executable).read_bytes()).hexdigest() == digest.lower(), "backend executable differs from requested pin"
    return SourceProofBackend.maledictus(executable, digest)


def _prove_outcomes(
    project: dict[str, object], backend: SourceProofBackend, changed: tuple[str, str] | None = None,
) -> dict[str, object]:
    root = Path(str(project["root"]))
    source = root / "app.py"
    source.write_text(_SOURCE, encoding="utf-8")
    contract_path = Path(str(project["contract"]))
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["outcomes"] = [
        {"type": name, "resources": {}, "metadata": {}}
        for name in ("WorkCompleted", "WorkIdle", "WorkRejected")
    ]
    contract_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    predicates = {
        "WorkCompleted": "result.value == input.value + 1",
        "WorkIdle": "not input.active",
        "WorkRejected": "result.value == input.value and input.value < 0",
    }
    if changed is not None:
        predicates[changed[0]] = changed[1]
    contract = load_contract(contract_path, source_root=root)
    fingerprint = source_fingerprint(root, exclude=["dag_contract.json", "english_requirements.json"])
    relations = [SourceRelation("outcome-" + name, "work", name, predicate) for name, predicate in predicates.items()]
    return verify_source_relations(
        contract, root, relations, backend, fingerprint, source_manifest_paths=["app.py"],
    )


def test_real_three_outcome_relations_prove_without_erasing_inapplicable_outcomes(
    project: dict[str, object], outcome_backend: SourceProofBackend,
) -> None:
    proof = _prove_outcomes(project, outcome_backend)
    assert proof["status"] == "proved"
    assert proof["covered_return_counts"] == {"app.py:work": 3}
    assert len(proof["relations"]) == 3


@pytest.mark.parametrize("changed", [
    ("WorkCompleted", "result.value == input.value + 2"),
    ("WorkIdle", "input.active"),
    ("WorkRejected", "result.value == input.value + 1"),
])
def test_real_wrong_outcome_predicate_is_semantically_refuted(
    project: dict[str, object], outcome_backend: SourceProofBackend, changed: tuple[str, str],
) -> None:
    with pytest.raises(RelationError) as caught:
        _prove_outcomes(project, outcome_backend, changed)
    message = str(caught.value)
    assert "source relational proof refused" in message
    assert "isinstance-type-mismatch" not in message, "frontend refusal is not a proof of predicate falsity"
    assert any(marker in message.lower() for marker in ("assert.failed", "postcondition", "counterexample", "model:")), message


def test_negative_outcome_guard_is_executed_not_trusted_as_a_compiler_hint() -> None:
    source = '''class A:
    pass
class B:
    pass
class Both(A, B):
    pass
def choose(value: A) -> A | B:
    return value
'''
    view, count = build_relation_proof_view(
        source, "choose", [SourceRelation("cannot-be-b", "choose", "B", "False")],
        annotate_results=False, return_modes=[{"B": "never"}],
    )
    namespace: dict[str, object] = {}
    exec(compile(view, "overlap_proof_view.py", "exec"), namespace)
    assert count == 1
    with pytest.raises(AssertionError):
        exec("choose(Both())", namespace)
