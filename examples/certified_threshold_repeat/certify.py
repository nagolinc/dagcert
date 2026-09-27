from __future__ import annotations

from pathlib import Path

from dagcert import EvidenceRecorder, TimingSample, issue_certificate, source_fingerprint
from dagcert.certificate import verify_certificate


def main() -> None:
    root = Path(__file__).resolve().parent
    contract = root / "dag_contract.json"
    requirements = root / "english_requirements.json"
    evidence = root / "artifacts" / "timings.jsonl"
    certificate = root / "artifacts" / "certificate.json"
    exclusions = [
        "dag_contract.json",
        "english_requirements.json",
        "artifacts/timings.jsonl",
        "artifacts/certificate.json",
    ]
    fingerprint = source_fingerprint(root, exclude=exclusions)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.unlink(missing_ok=True)
    recorder = EvidenceRecorder(evidence)
    for index in range(10):
        rejected = index == 9
        recorder.append(TimingSample(
            task_id="item.prepare",
            case="completion",
            value_ms=1,
            worker_id="preparation-worker",
            source_fingerprint=fingerprint,
            outcome_type="PreparationRejected" if rejected else "PreparedItem",
            resource_produced={} if rejected else {"prepared-items": 1},
        ))
    document = issue_certificate(
        contract,
        evidence,
        certificate,
        requirements_path=requirements,
        source_root=root,
    )
    verification = verify_certificate(
        certificate,
        contract_path=contract,
        evidence_path=evidence,
        requirements_path=requirements,
        source_root=root,
    )
    if not verification.valid:
        raise RuntimeError("verification failed: " + "; ".join(verification.problems))
    print(f"issued and verified {document['certificate_sha256']}")


if __name__ == "__main__":
    main()
