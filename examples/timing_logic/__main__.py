"""Check the mathematical family; optionally certify the actual release policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dagcert.certificate import issue_certificate, verify_certificate
from dagcert.linear_certificates import issue_math_certificate, verify_math_certificate

from .math_examples import examples
from .model import SOURCE_ROOT, contract_document, requirements_document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--certify", action="store_true",
        help="Also source-prove, issue and independently verify the timed release policy certificate.",
    )
    parser.add_argument("--output", type=Path, default=Path(".cache/timing-logic"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for example in examples():
        certificate = issue_math_certificate(example.variables, example.assumptions, example.conclusion)
        path = output / f"{example.name}.math.json"
        path.write_text(json.dumps(certificate, indent=2) + "\n", encoding="utf-8")
        result = verify_math_certificate(json.loads(path.read_text(encoding="utf-8")))
        if result.status != "valid":
            print(f"FAIL {example.name}: {result.reason}")
            return 1
        print(f"PASS mathematics: {example.name}")
    if not args.certify:
        print("Mathematical implications verified. These are NOT application certificates; use --certify.")
        return 0
    document = contract_document()
    contract_path = output / "dag_contract.json"
    requirements_path = output / "english_requirements.json"
    evidence_path = output / "timings.jsonl"
    certificate_path = output / "certificate.json"
    contract_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    requirements_path.write_text(json.dumps(requirements_document(document), indent=2) + "\n", encoding="utf-8")
    # Conditional source/algebra proofs do not need invented stopwatch evidence.
    evidence_path.write_text("", encoding="utf-8")
    issue_certificate(
        contract_path, evidence_path, certificate_path,
        requirements_path=requirements_path, source_root=SOURCE_ROOT,
    )
    verification = verify_certificate(
        certificate_path, contract_path=contract_path, evidence_path=evidence_path,
        requirements_path=requirements_path, source_root=SOURCE_ROOT,
    )
    if not verification.valid:
        print(f"Source certificate verification refused: {verification.problems}")
        return 1
    print(f"Source-bound timed release policy independently verified: {certificate_path}")
    print("Scope: the toy policy under its disclosed dispatch/platform envelope, not a complete storage cluster.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
