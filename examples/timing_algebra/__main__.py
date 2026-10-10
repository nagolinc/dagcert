"""Run the conditional timing derivation without claiming source certification."""

from __future__ import annotations

from pathlib import Path

from dagcert.analysis import analyze_contract
from dagcert.certificate import source_fingerprint
from dagcert.contract import load_contract
from dagcert.formula import evaluate_formula
from dagcert.requirements import audit_translation, load_requirements
from dagcert.temporal import prove_temporal_bound


def main() -> int:
    root = Path(__file__).resolve().parent
    contract = load_contract(root / "dag_contract.json", source_root=root)
    requirements = load_requirements(root / "english_requirements.json")
    analysis = analyze_contract(contract, (), source_fingerprint=source_fingerprint(root))
    audit = audit_translation(requirements, contract, selected_checkers=())
    if not analysis.passed or not audit.passed:
        print("Conditional model proof failed.")
        print(analysis)
        print(audit)
        return 1
    for claim in requirements.claims:
        if claim.formula is None:
            raise ValueError(f"Claim {claim.id} has no kernel formula")
        result = evaluate_formula(claim.formula, contract, analysis)
        print(f"{claim.id}: {'passed' if result.passed else 'failed'}")
        if not result.passed:
            print(result)
            return 1
    for state_claim in contract.state_claims:
        passed, explanation = prove_temporal_bound(state_claim.specification, contract)
        print(f"{state_claim.id}: {explanation}")
        if not passed:
            return 1
    print("Conditional model proof passed. No source certificate was issued.")
    print("The arrival, worker availability, duration, and dispatch envelopes are assumptions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
