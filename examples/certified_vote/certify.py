"""Measure the exact in-process operations, derive claims, issue, and verify."""

from pathlib import Path
from time import perf_counter, time
from typing import Callable

from dagcert import (
    EvidenceRecorder,
    TimingSample,
    issue_certificate,
    outcome_type,
    source_fingerprint,
    verify_certificate,
)
from .app import (
    CommittedTotal,
    PreviewTotal,
    VoteRequest,
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
            dict[str, int],
            dict[str, int],
            Callable[..., object],
        ],
        ...,
    ] = (
        ("vote.preview", "interface", {}, {}, preview_vote_total),
        (
            "vote.commit",
            "ledger",
            {},
            {"snapshot-work": 1, "summary-lag": 1},
            commit_vote_total,
        ),
        (
            "summary.advance",
            "summarizer",
            {"summary-lag": 1},
            {},
            advance_summary_generation,
        ),
        (
            "snapshot.render",
            "renderer",
            {"snapshot-work": 1},
            {},
            render_vote_snapshot,
        ),
    )
    for task_id, worker_id, consumed, produced, operation_callable in measured:
        for sample_index in range(10):
            started = perf_counter()
            if task_id in {"vote.preview", "vote.commit"}:
                request = (
                    VoteRequest(sample_index, 1)
                    if task_id == "vote.preview"
                    else PreviewTotal(sample_index + 1)
                )
                result = operation_callable(request)
            elif task_id == "summary.advance":
                result = operation_callable(CommittedTotal(sample_index))
            else:
                result = operation_callable(CommittedTotal(sample_index))
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
                outcome_type=outcome_type(result),
                resource_consumed=consumed,
                resource_produced=produced,
            ))

    issue_certificate(
        contract_path,
        evidence_path,
        certificate_path,
        source_root=root,
        requirements_path=requirements_path,
    )
    verification = verify_certificate(
        certificate_path,
        contract_path=contract_path,
        evidence_path=evidence_path,
        requirements_path=requirements_path,
        source_root=root,
    )
    if not verification.valid:
        raise RuntimeError("verification failed: " + "; ".join(verification.problems))
    print("issued and verified the exact in-process application certificate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
