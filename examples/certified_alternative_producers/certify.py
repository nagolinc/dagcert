from __future__ import annotations

from pathlib import Path

from dagcert import issue_certificate, verify_certificate


def main() -> None:
    root = Path(__file__).resolve().parent
    certificate = root / "artifacts" / "certificate.json"
    document = issue_certificate(
        root / "dag_contract.json",
        root / "artifacts" / "timings.jsonl",
        certificate,
        requirements_path=root / "english_requirements.json",
        source_root=root,
    )
    verification = verify_certificate(
        certificate,
        contract_path=root / "dag_contract.json",
        evidence_path=root / "artifacts" / "timings.jsonl",
        requirements_path=root / "english_requirements.json",
        source_root=root,
    )
    if not verification.valid:
        raise RuntimeError("verification failed: " + "; ".join(verification.problems))
    print(f"issued and verified {document['certificate_sha256']}")


if __name__ == "__main__":
    main()
