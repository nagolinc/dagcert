from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import pytest

from dagcert import (
    Contract,
    ContractError,
    EvidenceRecorder,
    ExternalContract,
    ExternalEvidenceMonitor,
    ExternalProvider,
    ExternalRaised,
    ExternalSuccess,
    ExternalTypeViolation,
    EnglishClaim,
    EnglishRequirements,
    Resource,
    ResourceEffect,
    Task,
    TaskErrorBudget,
    TaskOutcome,
    Timing,
    Worker,
    analyze_contract,
    check_python_sources,
    clear_runtime_violations,
    external_boundary,
    audit_translation,
    load_contract,
    load_evidence,
    monitor_external_boundaries,
    runtime_violations,
)
from dagcert.formula import evaluate_formula
from dagcert.source_types import ExternalSourceContract


@dataclass(frozen=True)
class _Request:
    value: str


@dataclass(frozen=True)
class _Parsed:
    path: str


def _runtime_contract() -> Contract:
    task = Task(
        "url.parse",
        "library",
        "_Request",
        "_Parsed | dagcert.runtime.ExternalRaised | dagcert.runtime.ExternalTypeViolation",
        resources={"parsed": ResourceEffect(produce=1)},
        timings={"call": Timing("duration", upper_ms=100, minimum_samples=1)},
        role="external",
        outcomes=(
            TaskOutcome("_Parsed", {"parsed": ResourceEffect(produce=1)}),
            TaskOutcome("dagcert.runtime.ExternalRaised"),
            TaskOutcome("dagcert.runtime.ExternalTypeViolation"),
        ),
        error_budget=TaskErrorBudget(
            "engineering_assumption", "call", ("_Parsed",), 0.0, 1,
        ),
        external_contract=ExternalContract(
            "url_contract.py",
            "urllib.parse.urlsplit returns the annotated parsed value",
            ExternalProvider("urllib.parse", ("urlsplit",)),
            "_Parsed",
            "call",
        ),
    )
    return Contract(
        "dagcert-contract/v6",
        (Worker("library", 1),),
        (task,),
        (Resource("parsed", 1),),
    )


def test_external_boundary_success_is_typed_and_recorded(tmp_path: Path) -> None:
    clear_runtime_violations()

    @external_boundary("url.parse")
    def parse(request: _Request) -> _Parsed:
        return _Parsed(request.value)

    evidence_path = tmp_path / "external.jsonl"
    monitor = ExternalEvidenceMonitor(
        _runtime_contract(), EvidenceRecorder(evidence_path), source_fingerprint="f" * 64,
    )
    with monitor_external_boundaries(monitor):
        result = parse(_Request("/image.png"))

    assert result == ExternalSuccess(_Parsed("/image.png"))
    assert runtime_violations() == ()
    samples = load_evidence(evidence_path)
    assert len(samples) == 1
    assert samples[0].outcome_type == "_Parsed"
    assert samples[0].resource_produced == {"parsed": 1.0}
    report = analyze_contract(
        _runtime_contract(), samples, source_fingerprint="f" * 64,
    )
    assert report.passed
    formula = {
        "gte": [
            {"external_success_probability_lower": "external-contract:url.parse"},
            1.0,
        ]
    }
    evaluated = evaluate_formula(formula, _runtime_contract(), report)
    assert evaluated.passed
    assert set(evaluated.primitive_refs) == {
        "external-contract:url.parse", "error-budget:url.parse",
    }
    requirements = EnglishRequirements(
        "dagcert-english-requirements/v2",
        (EnglishClaim(
            "stdlib-url-contract",
            "The declared urllib adapter returns its parsed value.",
            (
                "task:url.parse", "timing:url.parse/call",
                "external-contract:url.parse", "error-budget:url.parse",
            ),
            assumptions=("The pinned urllib implementation meets the declared adapter contract.",),
            basis="chance",
            formula=formula,
        ),),
    )
    assert audit_translation(requirements, _runtime_contract()).passed


def test_external_raise_and_wrong_return_are_visible_certificate_violations(
    tmp_path: Path,
) -> None:
    clear_runtime_violations()

    @external_boundary("url.parse")
    def raises(_request: _Request) -> _Parsed:
        raise ValueError("provider broke")

    @external_boundary("url.parse")
    def wrong(_request: _Request) -> _Parsed:
        return "not parsed"  # type: ignore[return-value]

    @external_boundary("url.parse")
    def wrong_input(request: _Request) -> _Parsed:
        return _Parsed(request.value)

    evidence_path = tmp_path / "external.jsonl"
    monitor = ExternalEvidenceMonitor(
        _runtime_contract(), EvidenceRecorder(evidence_path), source_fingerprint="f" * 64,
    )
    with monitor_external_boundaries(monitor):
        raised = raises(_Request("x"))
        mistyped = wrong(_Request("x"))
        bad_input = wrong_input("not a request")  # type: ignore[arg-type]

    assert isinstance(raised, ExternalRaised)
    assert isinstance(mistyped, ExternalTypeViolation)
    assert isinstance(bad_input, ExternalTypeViolation)
    assert len(runtime_violations()) == 3
    report = analyze_contract(
        _runtime_contract(), load_evidence(evidence_path), source_fingerprint="f" * 64,
    )
    assert not report.passed
    assert any(item.code == "error-budget-observed-rate-exceeded" for item in report.findings)


def test_v6_external_adapter_and_contractonly_stub_are_separate_and_exact(
    tmp_path: Path,
) -> None:
    (tmp_path / "boundary.py").write_text(
        "from dataclasses import dataclass\n"
        "from urllib.parse import urlsplit\n"
        "from dagcert.runtime import external_boundary\n\n"
        "@dataclass(frozen=True)\nclass RawUrl:\n    value: str\n\n"
        "@dataclass(frozen=True)\nclass ParsedUrl:\n    path: str\n\n"
        "@external_boundary('url.parse')\n"
        "def parse_url(request: RawUrl) -> ParsedUrl:\n"
        "    return ParsedUrl(urlsplit(request.value).path)\n",
        encoding="utf-8",
    )
    (tmp_path / "boundary_contract.py").write_text(
        "from dataclasses import dataclass\n"
        "from nagini_contracts.contracts import ContractOnly, Ensures, Result\n"
        "@dataclass(frozen=True)\nclass RawUrl:\n    value: str\n\n"
        "@dataclass(frozen=True)\nclass ParsedUrl:\n    path: str\n\n"
        "@ContractOnly\n"
        "def parse_url(request: RawUrl) -> ParsedUrl:\n"
        "    Ensures(Result() is not None)\n",
        encoding="utf-8",
    )
    contract_path = tmp_path / "dag_contract.json"
    contract_path.write_text(json.dumps({
        "schema": "dagcert-contract/v6",
        "workers": [{"id": "library", "concurrency": 1}],
        "resources": [{"id": "parsed", "capacity": 1, "initial": 0}],
        "tasks": [{
            "id": "url.parse",
            "role": "external",
            "worker": "library",
            "implementation": {"language": "python", "path": "boundary.py", "symbol": "parse_url"},
            "outcomes": [
                {"type": "ParsedUrl", "resources": {"parsed": {"produce": 1}}, "metadata": {}},
                {"type": "dagcert.runtime.ExternalRaised", "resources": {}, "metadata": {}},
                {"type": "dagcert.runtime.ExternalTypeViolation", "resources": {}, "metadata": {}},
            ],
            "error_budget": {
                "basis": "engineering_assumption",
                "evidence_case": "call",
                "good_outcomes": ["ParsedUrl"],
                "bad_event_probability_upper": 0,
                "minimum_observations": 1,
            },
            "external_contract": {
                "stub_path": "boundary_contract.py",
                "assumption": "urllib.parse.urlsplit returns ParsedUrl for every RawUrl",
                "provider": {"module": "urllib.parse", "symbols": ["urlsplit"]},
                "success_outcome": "ParsedUrl",
                "evidence_case": "call",
            },
            "depends_on": [],
            "timings": {"call": {"metric": "duration", "upper_ms": 100, "minimum_samples": 1}},
        }],
        "compositions": [],
        "metadata": {},
    }), encoding="utf-8")

    loaded = load_contract(contract_path, source_root=tmp_path)
    assert loaded.tasks[0].role == "external"
    assert loaded.tasks[0].source_signature is not None
    assert loaded.tasks[0].source_signature.outcome_types == (
        "ParsedUrl",
        "dagcert.runtime.ExternalRaised",
        "dagcert.runtime.ExternalTypeViolation",
    )
    signature = loaded.tasks[0].source_signature
    verification = check_python_sources(
        tmp_path,
        (signature,),
        source_fingerprint="f" * 64,
        proof_signatures=(),
        external_contracts=(ExternalSourceContract(
            "url.parse",
            "boundary.py",
            "parse_url",
            "boundary_contract.py",
            "urllib.parse",
            ("urlsplit",),
            "urllib.parse.urlsplit returns ParsedUrl for every RawUrl",
            signature,
        ),),
    )
    external = verification["external_contracts"]
    assert isinstance(external, list)
    assert external[0]["provider"]["module"] == "urllib.parse"
    assert external[0]["adapter"]["sha256"]
    assert external[0]["contract_stub"]["sha256"]

    stub_path = tmp_path / "boundary_contract.py"
    stub_path.write_text(
        stub_path.read_text(encoding="utf-8").replace(
            "Ensures(Result() is not None)", "Ensures(False)",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="Arbitrary proof axioms"):
        load_contract(contract_path, source_root=tmp_path)
