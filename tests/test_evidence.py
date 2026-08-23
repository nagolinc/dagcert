from pathlib import Path
import json

import pytest

from dagcert import EvidenceError, TimingSample, load_evidence


def test_timing_sample_rejects_wrong_runtime_types():
    with pytest.raises(EvidenceError, match="succeeded must be boolean"):
        TimingSample(
            task_id="task", case="duration", value_ms=1, worker_id="worker",
            source_fingerprint="fingerprint", succeeded="yes",  # type: ignore[arg-type]
        )


def test_evidence_loader_does_not_coerce_identifiers(tmp_path: Path):
    path = tmp_path / "evidence.jsonl"
    path.write_text(json.dumps({
        "task_id": 7,
        "case": "duration",
        "value_ms": 1,
        "worker_id": "worker",
        "source_fingerprint": "fingerprint",
        "succeeded": True,
        "recorded_at": 1,
    }) + "\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="task_id must be a nonempty string"):
        load_evidence(path)
