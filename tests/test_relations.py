from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path

import pytest

from dagcert import load_contract
from dagcert.relations import (
    RelationError, SourceRelation, build_relation_proof_view,
    parse_relation_predicate, verify_source_relations,
)


_SOURCE = '''from dataclasses import dataclass
from dagcert.runtime import operation

@dataclass
class Request:
    amount: int

@dataclass
class Complete:
    amount: int

@operation
def work(request: Request) -> Complete:
    if request.amount < 0:
        return Complete(0)
    return Complete(request.amount + 1)
'''


@pytest.mark.parametrize("predicate", [
    "result.amount >= 0",
    "input.amount < 0 or result.amount == input.amount + 1",
    "result.key == input.key and result.amount <= input.limit",
    "len(result.keys) <= len(input.keys)",
    "result.amount * 2 - input.amount >= -3",
])
def test_relation_predicates_are_parsed_without_evaluation(predicate: str) -> None:
    assert isinstance(parse_relation_predicate(predicate), ast.expr)


@pytest.mark.parametrize("predicate", [
    "__import__('os').system('echo unsafe')",
    "result.__class__ == input.__class__",
    "result.transform() == 1",
    "(lambda: True)()",
    "all(value for value in input.values)",
    "input.items[0] == result.amount",
    "len(input.items, bogus=True) == 0",
    "len == result.amount",
    "unknown == 1",
    "result.amount < 1e999",
    "",
])
def test_relation_predicate_rejects_unbound_or_executable_syntax(predicate: str) -> None:
    with pytest.raises(RelationError):
        parse_relation_predicate(predicate)


def _execute(source: str) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(compile(source, "proof_view.py", "exec"), namespace)
    return namespace


def test_every_return_is_asserted_and_original_source_is_unchanged() -> None:
    relation = SourceRelation("nonnegative", "work", "Complete", "result.amount >= 0")
    view, count = build_relation_proof_view(_SOURCE, "work", [relation])
    assert count == 2
    assert build_relation_proof_view(_SOURCE, "work", [relation]) == (view, count)
    namespace = _execute(view)
    request = namespace["Request"]
    work = namespace["work"]
    assert callable(request) and callable(work)
    assert work(request(-5)).amount == 0
    assert work(request(4)).amount == 5


def test_bad_early_return_cannot_escape_injected_assertion() -> None:
    relation = SourceRelation("positive", "work", "Complete", "result.amount > 0")
    view, _ = build_relation_proof_view(_SOURCE, "work", [relation])
    namespace = _execute(view)
    request = namespace["Request"]
    work = namespace["work"]
    assert callable(request) and callable(work)
    with pytest.raises(AssertionError):
        work(request(-5))


def test_relation_input_scalar_is_entry_value_even_when_mutated() -> None:
    source = _SOURCE[:_SOURCE.index("@operation")] + '''@operation
def work(request: Request) -> Complete:
    request.amount = request.amount + 1
    return Complete(request.amount)
'''
    relation = SourceRelation(
        "entry-value", "work", "Complete", "result.amount == input.amount + 1",
    )
    view, _ = build_relation_proof_view(source, "work", [relation])
    namespace = _execute(view)
    request = namespace["Request"]
    work = namespace["work"]
    assert callable(request) and callable(work)
    assert work(request(4)).amount == 5


def test_return_expression_is_evaluated_once() -> None:
    source = _SOURCE[:_SOURCE.index("@operation")] + '''calls = 0
def produce(amount: int) -> Complete:
    global calls
    calls += 1
    return Complete(amount)

@operation
def work(request: Request) -> Complete:
    return produce(request.amount)
'''
    relation = SourceRelation("identity", "work", "Complete", "result.amount == input.amount")
    view, _ = build_relation_proof_view(source, "work", [relation])
    namespace = _execute(view)
    request = namespace["Request"]
    work = namespace["work"]
    assert callable(request) and callable(work)
    assert work(request(4)).amount == 4
    assert namespace["calls"] == 1


def test_finalizer_mutation_is_refused_not_incorrectly_proved() -> None:
    source = _SOURCE[:_SOURCE.index("@operation")] + '''@operation
def work(request: Request) -> Complete:
    returned = Complete(1)
    try:
        return returned
    finally:
        returned.amount = -1
'''
    relation = SourceRelation("positive", "work", "Complete", "result.amount > 0")
    with pytest.raises(RelationError, match="postcondition support"):
        build_relation_proof_view(source, "work", [relation])


def test_shadowed_builtin_cannot_disable_assertions() -> None:
    source = "def isinstance(value: object, kind: object) -> bool:\n    return False\n" + _SOURCE
    relation = SourceRelation("positive", "work", "Complete", "result.amount > 0")
    with pytest.raises(RelationError, match="shadowed"):
        build_relation_proof_view(source, "work", [relation])


def test_imported_fake_postcondition_cannot_disable_native_proof() -> None:
    source = "from fake_contracts import Ensures\n" + _SOURCE
    relation = SourceRelation("positive", "work", "Complete", "result.amount > 0")
    with pytest.raises(RelationError, match="shadows canonical"):
        build_relation_proof_view(source, "work", [relation], backend_postconditions=True)


def test_other_outcomes_do_not_need_success_quantity_fields() -> None:
    source = _SOURCE.replace("@operation", "@dataclass\nclass Failed:\n    reason: str\n\n@operation")
    source = source.replace("-> Complete:", "-> Complete | Failed:")
    source = source.replace("return Complete(0)", "return Failed('negative')")
    relation = SourceRelation("positive", "work", "Complete", "result.amount > 0")
    view, _ = build_relation_proof_view(source, "work", [relation])
    namespace = _execute(view)
    request = namespace["Request"]
    work = namespace["work"]
    assert callable(request) and callable(work)
    assert type(work(request(-1))).__name__ == "Failed"


def test_real_nagini_proves_relation_and_binds_original_and_proof_sources(project: dict[str, object]) -> None:
    root = Path(str(project["root"]))
    contract = load_contract(Path(str(project["contract"])), source_root=root)
    before = (root / "app.py").read_bytes()
    result = verify_source_relations(
        contract, root,
        [SourceRelation("increment", "work", "WorkCompleted", "result.value == input.value + 1")],
        None, str(project["fingerprint"]), source_manifest_paths=["app.py"],
    )
    assert result["status"] == "proved"
    assert result["original_sources"] != result["proof_sources"]
    assert result["covered_return_counts"] == {"app.py:work": 1}
    assert (root / "app.py").read_bytes() == before


def test_real_nagini_refutes_false_source_relation(project: dict[str, object]) -> None:
    root = Path(str(project["root"]))
    contract = load_contract(Path(str(project["contract"])), source_root=root)
    with pytest.raises(RelationError, match="source relational proof refused"):
        verify_source_relations(
            contract, root,
            [SourceRelation("wrong-increment", "work", "WorkCompleted", "result.value == input.value + 2")],
            None, str(project["fingerprint"]), source_manifest_paths=["app.py"],
        )


def test_external_task_cannot_claim_application_relation(project: dict[str, object]) -> None:
    root = Path(str(project["root"]))
    contract = load_contract(Path(str(project["contract"])), source_root=root)
    contract = replace(contract, tasks=(replace(contract.tasks[0], role="external"),))
    with pytest.raises(RelationError, match="source-bound operation"):
        verify_source_relations(
            contract, root,
            [SourceRelation("wrong-boundary", "work", "WorkCompleted", "result.value == input.value")],
            None, str(project["fingerprint"]), source_manifest_paths=["app.py"],
        )


@pytest.mark.parametrize("expected_delta,proves", [(2, True), (1, False)])
def test_real_nagini_postcondition_accounts_for_finalizer_return(
    project: dict[str, object], expected_delta: int, proves: bool,
) -> None:
    root = Path(str(project["root"]))
    source = (root / "app.py").read_text(encoding="utf-8")
    source = source[:source.index("@operation")] + '''@operation
def work(request: WorkInput) -> WorkCompleted:
    try:
        return WorkCompleted(request.value + 1)
    finally:
        return WorkCompleted(request.value + 2)
'''
    (root / "app.py").write_text(source, encoding="utf-8")
    contract = load_contract(Path(str(project["contract"])), source_root=root)
    relations = [SourceRelation(
        "after-cleanup", "work", "WorkCompleted",
        f"result.value == input.value + {expected_delta}",
    )]
    if proves:
        proof = verify_source_relations(
            contract, root, relations, None, str(project["fingerprint"]),
            source_manifest_paths=["app.py"],
        )
        assert proof["owner_transformations"] == {"app.py:work": "nagini-native-postconditions"}
    else:
        with pytest.raises(RelationError, match="source relational proof refused"):
            verify_source_relations(
                contract, root, relations, None, str(project["fingerprint"]),
                source_manifest_paths=["app.py"],
            )


@pytest.mark.parametrize("minimum,proves", [(1, True), (2, False)])
def test_real_nagini_closed_union_keeps_failure_outcome_and_proves_success_relation(
    project: dict[str, object], minimum: int, proves: bool,
) -> None:
    root = Path(str(project["root"]))
    source = (root / "app.py").read_text(encoding="utf-8")
    source = "from typing import Union\n" + source[:source.index("@operation")] + '''@dataclass(frozen=True)
class WorkRejected:
    reason: str

@operation
def work(request: WorkInput) -> Union[WorkCompleted, WorkRejected]:
    if request.value < 0:
        return WorkRejected("negative")
    return WorkCompleted(request.value + 1)
'''
    (root / "app.py").write_text(source, encoding="utf-8")
    contract_path = Path(str(project["contract"]))
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    raw["tasks"][0]["outcomes"].append({"type": "WorkRejected", "resources": {}, "metadata": {}})
    contract_path.write_text(json.dumps(raw), encoding="utf-8")
    contract = load_contract(contract_path, source_root=root)
    requested = [SourceRelation("positive-success", "work", "WorkCompleted", f"result.value >= {minimum}")]
    if not proves:
        with pytest.raises(RelationError, match="Verification failed"):
            verify_source_relations(
                contract, root, requested, None, str(project["fingerprint"]),
                source_manifest_paths=["app.py"],
            )
        return
    proof = verify_source_relations(
        contract, root, requested, None, str(project["fingerprint"]),
        source_manifest_paths=["app.py"],
    )
    assert proof["covered_return_counts"] == {"app.py:work": 2}
    assert proof["owner_transformations"] == {"app.py:work": "all-return-assertions"}


def test_compiler_return_coverage_preserves_subclass_outcomes(tmp_path: Path) -> None:
    from dagcert.relation_types import compiler_return_bindings

    (tmp_path / "sample.py").write_text('''class Base:
    pass

class Child(Base):
    pass

class Separate:
    pass

def choose() -> Base:
    return Child()
''', encoding="utf-8")
    modes, provenance = compiler_return_bindings(
        tmp_path, ["sample.py"], {("sample.py", "choose"): ("Base", "Child", "Separate")},
    )
    assert modes[("sample.py", "choose")] == [{"Base": "always", "Child": "always", "Separate": "never"}]
    assert provenance["checker"] == "mypy"


def test_compiler_return_coverage_refuses_any(tmp_path: Path) -> None:
    from dagcert.relation_types import RelationTypeError, compiler_return_bindings

    (tmp_path / "sample.py").write_text('''from typing import Any
class Completed:
    pass
def choose(value: Any) -> Completed:
    return value
''', encoding="utf-8")
    with pytest.raises(RelationTypeError, match="strict mypy"):
        compiler_return_bindings(tmp_path, ["sample.py"], {("sample.py", "choose"): ("Completed",)})


def test_compiler_disjoint_hint_still_requires_semantic_inapplicability() -> None:
    source = '''from typing import Union
class A:
    pass
class B:
    pass
class Both(A, B):
    pass
def choose(value: A) -> Union[A, B]:
    return value
'''
    transformed, count = build_relation_proof_view(
        source, "choose", [SourceRelation("b-condition", "choose", "B", "False")],
        annotate_results=False, return_modes=[{"B": "never"}],
    )
    scope: dict[str, object] = {}
    exec(transformed, scope)
    assert count == 1
    # The compiler's disjointness hint never removes the obligation. A real
    # overlapping object must fail the proof-view assertion, not pass vacuously.
    with pytest.raises(AssertionError):
        exec("choose(Both())", scope)
