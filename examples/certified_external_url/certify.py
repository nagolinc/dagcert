from __future__ import annotations

from pathlib import Path
import sys
from time import perf_counter

from dagcert import (
    EvidenceRecorder,
    ExternalEvidenceMonitor,
    ExternalSuccess,
    TimingSample,
    issue_certificate,
    load_contract,
    monitor_external_boundaries,
    outcome_type,
    source_fingerprint,
    verify_certificate,
)

_MODULE_ROOT = str(Path(__file__).resolve().parent)
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from app import accept_parsed_url
from boundary import parse_url
from types_model import RawUrl


def main(root: Path | None = None) -> int:
    app_root = (root or Path(__file__).resolve().parent).resolve()
    artifacts = app_root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    contract_path = app_root / "dag_contract.json"
    requirements_path = app_root / "english_requirements.json"
    evidence_path = artifacts / "timings.jsonl"
    certificate_path = artifacts / "certificate.json"
    evidence_path.write_text("", encoding="utf-8")
    fingerprint = source_fingerprint(app_root, exclude=(
        "dag_contract.json", "english_requirements.json",
        "artifacts/timings.jsonl", "artifacts/certificate.json",
    ))
    contract = load_contract(contract_path, source_root=app_root)
    recorder = EvidenceRecorder(evidence_path)
    monitor = ExternalEvidenceMonitor(
        contract, recorder, source_fingerprint=fingerprint,
    )
    for value in ("/one.png?x=1", "/two.png#preview", "/three.png"):
        with monitor_external_boundaries(monitor):
            parsed = parse_url(RawUrl(value))
        if not isinstance(parsed, ExternalSuccess):
            continue
        started = perf_counter()
        accepted = accept_parsed_url(parsed.value)
        recorder.append(TimingSample(
            task_id="url.accept",
            case="completion",
            value_ms=(perf_counter() - started) * 1000,
            worker_id="application",
            source_fingerprint=fingerprint,
            outcome_type=outcome_type(accepted),
            resource_consumed={"parsed-url": 1},
        ))
    issue_certificate(
        contract_path,
        evidence_path,
        certificate_path,
        requirements_path=requirements_path,
        source_root=app_root,
    )
    result = verify_certificate(
        certificate_path,
        contract_path=contract_path,
        evidence_path=evidence_path,
        requirements_path=requirements_path,
        source_root=app_root,
    )
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
