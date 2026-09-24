"""Measure, issue, and verify the generic Dagcert v7 pipeline example."""

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

from pipeline import (
    ChecksummedJob,
    PublishInput,
    RawJob,
    checksum,
    prepare,
    publish,
    validate,
)


def _measure(callable_object, argument):
    started = perf_counter()
    result = callable_object(argument)
    return result, (perf_counter() - started) * 1000


def main(
    root: Path | None = None,
    *,
    proof_backend_executable: Path | None = None,
) -> int:
    app_root = (root or Path(__file__).resolve().parent).resolve()
    artifacts = app_root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    contract_path = app_root / "dag_contract.json"
    requirements_path = app_root / "english_requirements.json"
    evidence_path = artifacts / "timings.jsonl"
    certificate_path = artifacts / "certificate.json"
    evidence_path.write_text("", encoding="utf-8")
    fingerprint = source_fingerprint(
        app_root,
        exclude=(
            "dag_contract.json",
            "english_requirements.json",
            "artifacts/timings.jsonl",
            "artifacts/certificate.json",
        ),
    )
    recorder = EvidenceRecorder(evidence_path)
    for value in range(5):
        prepared, prepare_ms = _measure(prepare, RawJob(value))
        recorder.append(TimingSample(
            "prepare", "duration", prepare_ms, "preparer", fingerprint,
            outcome_type=outcome_type(prepared),
            start_resource_consumed={"free": 1},
            start_resource_produced={"preparing": 1},
            resource_consumed={"preparing": 1},
            resource_produced={"ready": 1},
        ))
        validated, validate_ms = _measure(validate, prepared)
        recorder.append(TimingSample(
            "validate", "duration", validate_ms, "validator", fingerprint,
            outcome_type=outcome_type(validated),
        ))
        checked, checksum_ms = _measure(checksum, prepared)
        assert isinstance(checked, ChecksummedJob)
        recorder.append(TimingSample(
            "checksum", "duration", checksum_ms, "hasher", fingerprint,
            outcome_type=outcome_type(checked),
        ))
        published, publish_ms = _measure(
            publish,
            PublishInput(validation=validated, checksum=checked),
        )
        recorder.append(TimingSample(
            "publish", "duration", publish_ms, "publisher", fingerprint,
            outcome_type=outcome_type(published),
            start_resource_consumed={"ready": 1},
            start_resource_produced={"running": 1},
            resource_consumed={"running": 1},
            resource_produced={"free": 1},
        ))
    backend = None
    if proof_backend_executable is not None:
        backend = SourceProofBackend.maledictus(
            proof_backend_executable,
            sha256(proof_backend_executable.read_bytes()).hexdigest(),
        )
    issue_certificate(
        contract_path,
        evidence_path,
        certificate_path,
        requirements_path=requirements_path,
        source_root=app_root,
        proof_backend=backend,
    )
    verification = verify_certificate(
        certificate_path,
        contract_path=contract_path,
        evidence_path=evidence_path,
        requirements_path=requirements_path,
        source_root=app_root,
        proof_backend=backend,
    )
    return 0 if verification.valid else 1


if __name__ == "__main__":
    backend_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    raise SystemExit(main(proof_backend_executable=backend_path))
