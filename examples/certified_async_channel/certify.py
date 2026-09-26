"""Exercise the real queue, issue the certificate, and verify it."""

from pathlib import Path
import sys
from time import perf_counter, time
from typing import Callable, TypeVar

from dagcert import (
    EvidenceRecorder,
    ExternalSuccess,
    TimingSample,
    issue_certificate,
    source_fingerprint,
    verify_certificate,
)

MODULE_ROOT = str(Path(__file__).resolve().parent)
if MODULE_ROOT not in sys.path:
    sys.path.insert(0, MODULE_ROOT)


from app import (
    Delivered,
    JobTaken,
    NewJob,
    PreparedJob,
    QueuePutRequest,
    QueuePutResponse,
    QueueTakePolicy,
    QueueTakeRequest,
    QueueTakeResponse,
    build_put_request,
    build_take_request,
    classify_put,
    classify_take,
    deliver,
    prepare_job,
)
from external_get import get_job
from external_put import put_job


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


def _timed(operation: Callable[[InputT], OutputT], request: InputT) -> tuple[OutputT, float]:
    started = perf_counter()
    result = operation(request)
    return result, (perf_counter() - started) * 1000


def _record(
    recorder: EvidenceRecorder,
    fingerprint: str,
    *,
    task: str,
    worker: str,
    case: str,
    elapsed_ms: float,
    outcome: str,
    produced: dict[str, int] | None = None,
    consumed: dict[str, int] | None = None,
) -> None:
    recorder.append(TimingSample(
        task_id=task,
        case=case,
        value_ms=elapsed_ms,
        worker_id=worker,
        source_fingerprint=fingerprint,
        recorded_at=time(),
        outcome_type=outcome,
        resource_produced=produced or {},
        resource_consumed=consumed or {},
    ))


def collect(root: Path) -> Path:
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    evidence = artifacts / "timings.jsonl"
    evidence.unlink(missing_ok=True)
    fingerprint = source_fingerprint(
        root,
        exclude=(
            "dag_contract.json",
            "english_requirements.json",
            "artifacts/timings.jsonl",
            "artifacts/certificate.json",
        ),
    )
    recorder = EvidenceRecorder(evidence)

    for index in range(10):
        prepared, elapsed = _timed(prepare_job, NewJob(f"job-{index}"))
        _record(
            recorder,
            fingerprint,
            task="job.prepare",
            worker="producer",
            case="completion",
            elapsed_ms=elapsed,
            outcome="PreparedJob",
        )
        put_request, elapsed = _timed(build_put_request, prepared)
        _record(
            recorder,
            fingerprint,
            task="queue.put-request.build",
            worker="producer",
            case="completion",
            elapsed_ms=elapsed,
            outcome="QueuePutRequest",
        )
        put_boundary, elapsed = _timed(put_job, put_request)
        if not isinstance(put_boundary, ExternalSuccess):
            raise RuntimeError(f"queue put boundary failed: {put_boundary}")
        _record(
            recorder,
            fingerprint,
            task="stdlib.queue.put",
            worker="producer",
            case="call",
            elapsed_ms=elapsed,
            outcome="QueuePutResponse",
        )
        queued, elapsed = _timed(classify_put, put_boundary.value)
        if not isinstance(queued, PreparedJob):
            raise RuntimeError(f"queue put was not admitted: {queued}")
        _record(
            recorder,
            fingerprint,
            task="queue.put.classify",
            worker="producer",
            case="completion",
            elapsed_ms=elapsed,
            outcome="PreparedJob",
            produced={"prepared-job-count": 1},
        )

    for index in range(10):
        take_request, elapsed = _timed(build_take_request, QueueTakePolicy(False))
        _record(
            recorder,
            fingerprint,
            task="queue.take-request.build",
            worker="consumer",
            case="completion",
            elapsed_ms=elapsed,
            outcome="QueueTakeRequest",
        )
        take_boundary, elapsed = _timed(get_job, take_request)
        if not isinstance(take_boundary, ExternalSuccess):
            raise RuntimeError(f"queue get boundary failed: {take_boundary}")
        _record(
            recorder,
            fingerprint,
            task="stdlib.queue.get",
            worker="consumer",
            case="call",
            elapsed_ms=elapsed,
            outcome="QueueTakeResponse",
        )
        taken, elapsed = _timed(classify_take, take_boundary.value)
        if not isinstance(taken, JobTaken):
            raise RuntimeError(f"queue take did not return a job: {taken}")
        _record(
            recorder,
            fingerprint,
            task="queue.take.classify",
            worker="consumer",
            case="completion",
            elapsed_ms=elapsed,
            outcome="JobTaken",
            consumed={"prepared-job-count": 1},
        )
        delivered, elapsed = _timed(deliver, taken)
        if not isinstance(delivered, Delivered) or delivered.value != f"job-{index}":
            raise RuntimeError(f"queue changed message order or identity: {delivered}")
        _record(
            recorder,
            fingerprint,
            task="job.deliver",
            worker="consumer",
            case="completion",
            elapsed_ms=elapsed,
            outcome="Delivered",
        )
    return evidence


def main() -> int:
    root = Path(__file__).parent.resolve()
    evidence = collect(root)
    certificate = root / "artifacts" / "certificate.json"
    issue_certificate(
        root / "dag_contract.json",
        evidence,
        certificate,
        requirements_path=root / "english_requirements.json",
        source_root=root,
    )
    verification = verify_certificate(
        certificate,
        contract_path=root / "dag_contract.json",
        evidence_path=evidence,
        requirements_path=root / "english_requirements.json",
        source_root=root,
    )
    if not verification.valid:
        raise RuntimeError("verification failed: " + "; ".join(verification.problems))
    print(f"issued and verified {certificate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
