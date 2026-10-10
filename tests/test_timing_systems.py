"""The shipped variable-output example carries a real numerical chance claim."""

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from typing import Any

import pytest

from dagcert.analysis import analyze_contract
from dagcert.contract import Contract, load_contract
from dagcert.formula import FormulaError, evaluate_formula
from dagcert.requirements import audit_translation, load_requirements
from dagcert.temporal import temporal_failure_upper
from examples.timing_systems.invariants import SOURCE_ROOT
from examples.timing_systems.models import contract_document, requirements_document


def _load(document: dict[str, Any], tmp_path: Path) -> Contract:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return load_contract(path, source_root=SOURCE_ROOT)


def test_published_streaming_claim_uses_four_whole_lifetime_budgets(tmp_path: Path) -> None:
    document = contract_document()
    contract = _load(document, tmp_path)
    stream = contract.state_claim_by_id["stream.infinite-reserve"]
    envelopes = stream.specification["network"]["envelopes"]
    assert len(envelopes) == 4
    assert all(row["horizon_ms"] is None for row in envelopes)
    assert all(Fraction(row["failure_probability_upper"]) == Fraction(1, 10000) for row in envelopes)
    assert temporal_failure_upper(stream.specification) == Fraction(1, 2500)

    requirements_path = tmp_path / "requirements.json"
    requirements_path.write_text(json.dumps(requirements_document(document), indent=2), encoding="utf-8")
    requirements = load_requirements(requirements_path)
    audit = audit_translation(requirements, contract, selected_checkers=())
    assert audit.passed, audit.findings
    claim = requirements.claims[0]
    assert claim.basis == "chance" and claim.formula is not None
    analysis = analyze_contract(contract, (), source_fingerprint="a" * 64)
    assert evaluate_formula(claim.formula, contract, analysis).passed
    stronger = {"gte": [{"state_claim_success_probability_lower": "state-claim:stream.infinite-reserve"}, 0.9997]}
    assert not evaluate_formula(stronger, contract, analysis).passed


def test_larger_envelope_budget_does_not_silently_lower_the_published_target(tmp_path: Path) -> None:
    document = contract_document()
    published_formula = requirements_document(document)["claims"][0]["formula"]
    document["state_claims"][-1]["network"]["envelopes"][0]["failure_probability_upper"] = "1/1000"
    contract = _load(document, tmp_path)
    analysis = analyze_contract(contract, (), source_fingerprint="a" * 64)
    assert not evaluate_formula(published_formula, contract, analysis).passed


def test_small_failure_budget_does_not_replace_the_actual_reserve_proof(tmp_path: Path) -> None:
    document = deepcopy(contract_document())
    formula = requirements_document(document)["claims"][0]["formula"]
    workload = next(item for item in document["state_claims"][-1]["network"]["envelopes"]
                    if item["kind"] == "workload")
    workload["excess_work"] = 12000
    contract = _load(document, tmp_path)
    analysis = analyze_contract(contract, (), source_fingerprint="a" * 64)
    with pytest.raises(FormulaError, match="state claim stream.infinite-reserve failed"):
        evaluate_formula(formula, contract, analysis)
