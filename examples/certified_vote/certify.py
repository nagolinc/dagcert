"""Measure the exact in-process operations, derive claims, issue, and verify."""

from pathlib import Path
from time import perf_counter, time
from typing import Callable

from dagcert import (
    CheckContext,
    EvidenceRecorder,
    TimingSample,
    issue_certificate,
    load_contract,
    load_evidence,
    load_requirements,
    run_checker,
    sha256_file,
    source_fingerprint,
    verify_certificate,
)
from examples.optional_flow_checker import LagClaim, SupplyClaim, check_flow_guarantees

from .app import (
    advance_summary_generation,
    commit_vote_total,
    preview_vote_total,
    render_vote_snapshot,
)


def main(source_root: Path | None = None) -> int:
    root = (source_root or Path(__file__).parent).resolve()
    contract_path = root / "dag_contract.json"
    requirements_path = root / "english_requirements.json"
    evidence_path = root / "artifacts" / "timings.jsonl"
    check_path = root / "artifacts" / "flow-guarantees.json"
    certificate_path = root / "artifacts" / "certificate.json"
    evidence_path.parent.mkdir(exist_ok=True)
    evidence_path.unlink(missing_ok=True)

    fingerprint = source_fingerprint(
        root, exclude=["dag_contract.json", "english_requirements.json"]
    )
    recorder = EvidenceRecorder(evidence_path)
    measured: tuple[
        tuple[
            str,
            str,
            str,
            str,
            dict[str, int],
            dict[str, int],
            Callable[..., object],
        ],
        ...,
    ] = (
        ("vote.preview", "interface", "VoteDelta", "PreviewTotal", {}, {}, preview_vote_total),
        (
            "vote.commit",
            "ledger",
            "VoteDelta",
            "CommittedTotal",
            {},
            {"snapshot-work": 1, "summary-lag": 1},
            commit_vote_total,
        ),
        (
            "summary.advance",
            "summarizer",
            "Generation",
            "SummaryGeneration",
            {"summary-lag": 1},
            {},
            advance_summary_generation,
        ),
        (
            "snapshot.render",
            "renderer",
            "VoteTotal",
            "TextSnapshot",
            {"snapshot-work": 1},
            {},
            render_vote_snapshot,
        ),
    )
    for task_id, worker_id, input_type, output_type, consumed, produced, operation in measured:
        for sample_index in range(10):
            started = perf_counter()
            if task_id in {"vote.preview", "vote.commit"}:
                result = operation(sample_index, 1)
            else:
                result = operation(sample_index)
            elapsed_ms = (perf_counter() - started) * 1000
            if result is None:
                raise RuntimeError(f"{task_id} did not produce its declared output")
            recorder.append(TimingSample(
                task_id=task_id,
                case="completion",
                value_ms=elapsed_ms,
                worker_id=worker_id,
                source_fingerprint=fingerprint,
                recorded_at=time(),
                observed_worker_concurrency=1,
                observed_input_type=input_type,
                observed_output_type=output_type,
                resource_consumed=consumed,
                resource_produced=produced,
            ))

    contract = load_contract(contract_path)
    context = CheckContext(
        contract=contract,
        timings=load_evidence(evidence_path),
        source_root=root,
        source_fingerprint=fingerprint,
        contract_sha256=sha256_file(contract_path),
        evidence_sha256=sha256_file(evidence_path),
        requirements=load_requirements(requirements_path),
        requirements_sha256=sha256_file(requirements_path),
    )
    run_checker(
        lambda current: check_flow_guarantees(
            current,
            supply=SupplyClaim(
                "snapshot.render", "service-envelope", "vote.commit", "cadence", "snapshot-work"
            ),
            lag=LagClaim(
                "vote.commit", "cadence", "summary.advance", "service-envelope", "summary-lag", 3
            ),
        ),
        context,
        check_path,
    )
    issue_certificate(
        contract_path,
        evidence_path,
        certificate_path,
        source_root=root,
        requirements_path=requirements_path,
        check_result_paths=[check_path],
    )
    verification = verify_certificate(
        certificate_path,
        contract_path=contract_path,
        evidence_path=evidence_path,
        requirements_path=requirements_path,
        source_root=root,
        check_result_paths=[check_path],
    )
    if not verification.valid:
        raise RuntimeError("verification failed: " + "; ".join(verification.problems))
    print("issued and verified the exact in-process application certificate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
