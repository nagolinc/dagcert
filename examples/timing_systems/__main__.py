"""Run the models; optionally issue and independently verify their source certificate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dagcert.analysis import analyze_contract
from dagcert.certificate import issue_certificate, source_fingerprint, verify_certificate
from dagcert.contract import load_contract
from dagcert.formula import evaluate_formula
from dagcert.requirements import audit_translation, load_requirements
from dagcert.state_model import prove_state_claim

from .invariants import SOURCE_ROOT
from .models import contract_document, requirements_document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certify", action="store_true", help="Run strict mypy and the pinned Nagini proof backend, issue, then independently verify.")
    parser.add_argument("--output", type=Path, default=Path(".cache/timing-systems"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    contract_path, requirements_path = output / "dag_contract.json", output / "english_requirements.json"
    evidence_path, certificate_path = output / "timings.jsonl", output / "certificate.json"
    document = contract_document()
    contract_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    requirements_path.write_text(json.dumps(requirements_document(document), indent=2) + "\n", encoding="utf-8")
    # No benchmark measurements are needed to prove conditional arithmetic/source statements.
    evidence_path.write_text("", encoding="utf-8")
    contract = load_contract(contract_path, source_root=SOURCE_ROOT)
    requirements = load_requirements(requirements_path)
    analysis = analyze_contract(contract, (), source_fingerprint=source_fingerprint(SOURCE_ROOT))
    audit = audit_translation(requirements, contract, selected_checkers=())
    if not analysis.passed or not audit.passed:
        print(analysis)
        print(audit)
        return 1
    for claim in contract.state_claims:
        proof = prove_state_claim(claim, contract, analysis)
        print(f"{claim.id}: {'PASS' if proof.passed else 'FAIL'} — {proof.summary}")
        if not proof.passed:
            return 1
    for claim in requirements.claims:
        if claim.formula is None or not evaluate_formula(claim.formula, contract, analysis).passed:
            print(f"Requirement failed: {claim.id}")
            return 1
    if not args.certify:
        print("Conditional model checks passed. Source certification has NOT run; use --certify.")
        print(f"Inspectable inputs: {output}")
        return 0
    certificate = issue_certificate(
        contract_path, evidence_path, certificate_path,
        requirements_path=requirements_path, source_root=SOURCE_ROOT,
    )
    verified = verify_certificate(
        certificate_path, contract_path=contract_path, evidence_path=evidence_path,
        requirements_path=requirements_path, source_root=SOURCE_ROOT,
    )
    if not verified.valid:
        print(verified)
        return 1
    print(f"Source certificate independently verified: {certificate_path}")
    print(f"Exact source: {certificate['source_fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
