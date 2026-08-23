from __future__ import annotations

from pathlib import Path
import json

import pytest

from dagcert import (
    EvidenceRecorder,
    TimingSample,
    load_contract,
    load_evidence,
    load_requirements,
    source_fingerprint,
)


@pytest.fixture
def project(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "app"
    root.mkdir()
    (root / "app.py").write_text("def work(value: int) -> int:\n    return value + 1\n", encoding="utf-8")
    contract = root / "dag_contract.json"
    contract.write_text(json.dumps({
        "schema": "dagcert-contract/v2",
        "workers": [{"id": "worker", "concurrency": 2}],
        "resources": [{"id": "state", "capacity": 1, "initial": 0}],
        "tasks": [{
            "id": "work", "worker": "worker", "input_type": "int", "output_type": "int",
            "depends_on": [], "resources": {"state": {"acquire": 1}},
            "timings": {"normal": {
                "metric": "duration", "upper_ms": 10, "minimum_samples": 3,
                "policy": "max", "safety_factor": 1.3,
            }},
        }],
    }, indent=2), encoding="utf-8")
    requirements = root / "english_requirements.json"
    requirements.write_text(json.dumps({
        "schema": "dagcert-english-requirements/v1",
        "claims": [{
            "id": "work-completes",
            "statement": "The declared work task completes within 10 ms for the measured source.",
            "primitive_refs": ["task:work", "timing:work/normal"],
            "checker_refs": [],
            "assumptions": [],
        }],
        "metadata": {},
    }, indent=2), encoding="utf-8")
    evidence = root / "artifacts" / "timings.jsonl"
    fingerprint = source_fingerprint(
        root, exclude=["dag_contract.json", "english_requirements.json"]
    )
    recorder = EvidenceRecorder(evidence)
    for duration in (1.0, 2.0, 3.0):
        recorder.append(TimingSample(
            task_id="work", case="normal", value_ms=duration, worker_id="worker",
            source_fingerprint=fingerprint, observed_worker_concurrency=2,
            observed_input_type="int", observed_output_type="int",
            resource_acquired={"state": 1},
        ))
    return {
        "root": root,
        "contract": contract,
        "evidence": evidence,
        "requirements": requirements,
        "fingerprint": fingerprint,
        "loaded_contract": load_contract(contract),
        "loaded_evidence": load_evidence(evidence),
        "loaded_requirements": load_requirements(requirements),
    }
