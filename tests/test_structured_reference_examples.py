from __future__ import annotations

import json
from pathlib import Path

from dagcert.analysis import analyze_contract
from dagcert.contract import load_contract
from dagcert.evidence import load_evidence
from dagcert.formula import evaluate_formula
from dagcert.requirements import audit_translation, load_requirements


def _assert_example_claims(
    root: Path, *, certificate_schema: str = "dagcert-certificate/v11",
) -> None:
    contract = load_contract(root / "dag_contract.json", source_root=root)
    requirements = load_requirements(root / "english_requirements.json")
    evidence = load_evidence(root / "artifacts" / "timings.jsonl")
    certificate = json.loads(
        (root / "artifacts" / "certificate.json").read_text(encoding="utf-8")
    )
    analysis = analyze_contract(
        contract,
        evidence,
        source_fingerprint=certificate["source_fingerprint"],
    )

    assert certificate["schema"] == certificate_schema
    assert analysis.passed
    assert audit_translation(requirements, contract, selected_checkers=()).passed
    for claim in requirements.claims:
        assert claim.formula is not None
        assert evaluate_formula(claim.formula, contract, analysis).passed


def test_structured_worker_pipeline_v11_example_passes() -> None:
    root = Path(__file__).parents[1] / "examples" / "certified_structured_pipeline"
    _assert_example_claims(root)


def test_typescript_leaf_v11_example_passes() -> None:
    root = Path(__file__).parents[1] / "examples" / "certified_typescript_leaf"
    _assert_example_claims(root)


def test_async_channel_v12_example_passes() -> None:
    root = Path(__file__).parents[1] / "examples" / "certified_async_channel"
    _assert_example_claims(root, certificate_schema="dagcert-certificate/v12")


def test_browser_fetch_v13_example_passes() -> None:
    root = Path(__file__).parents[1] / "examples" / "certified_browser_fetch"
    _assert_example_claims(root, certificate_schema="dagcert-certificate/v13")


def test_alternative_producers_v14_example_passes() -> None:
    root = Path(__file__).parents[1] / "examples" / "certified_alternative_producers"
    _assert_example_claims(root, certificate_schema="dagcert-certificate/v14")
