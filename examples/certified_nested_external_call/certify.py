"""Issue and verify the one-task nested external-call example."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
from time import perf_counter

from dagcert import (
    EvidenceRecorder,
    TimingSample,
    issue_certificate,
    outcome_type,
    source_fingerprint,
    verify_certificate,
)
from dagcert.source_types import SourceProofBackend

_MODULE_ROOT = str(Path(__file__).resolve().parent)
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from app import NormalizeRequest, normalize_url


def main(executable: Path, root: Path | None = None) -> int:
    app_root = (root or Path(__file__).resolve().parent).resolve()
    artifacts = app_root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    evidence = artifacts / "timings.jsonl"
    evidence.write_text("", encoding="utf-8")
    fingerprint = source_fingerprint(
        app_root,
        exclude=(
            "dag_contract.json",
            "english_requirements.json",
            "artifacts/timings.jsonl",
            "artifacts/certificate.json",
        ),
    )
    recorder = EvidenceRecorder(evidence)
    for value in (" /A%20B ", "/SECOND", "/third"):
        started = perf_counter()
        result = normalize_url(NormalizeRequest(value))
        recorder.append(TimingSample(
            "url.normalize",
            "completion",
            (perf_counter() - started) * 1000,
            "application",
            fingerprint,
            outcome_type=outcome_type(result),
        ))
    backend = SourceProofBackend.maledictus(
        executable,
        sha256(executable.read_bytes()).hexdigest(),
    )
    certificate = artifacts / "certificate.json"
    contract = app_root / "dag_contract.json"
    requirements = app_root / "english_requirements.json"
    issue_certificate(
        contract,
        evidence,
        certificate,
        requirements_path=requirements,
        source_root=app_root,
        proof_backend=backend,
    )
    verification = verify_certificate(
        certificate,
        contract_path=contract,
        evidence_path=evidence,
        requirements_path=requirements,
        source_root=app_root,
        proof_backend=backend,
    )
    return 0 if verification.valid else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: python -m examples.certified_nested_external_call.certify PATH"
        )
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
