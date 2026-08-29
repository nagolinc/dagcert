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


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    """Confine repository-local disposable output to the single .cache tree."""
    root = Path(str(config.rootpath)).resolve()
    safe_cache_root = (root / ".cache").resolve()
    cache_value = Path(str(config.getini("cache_dir")))
    cache_path = (
        cache_value if cache_value.is_absolute() else root / cache_value
    ).resolve()
    if _is_within(cache_path, root) and not _is_within(cache_path, safe_cache_root):
        raise pytest.UsageError(
            "pytest cache_dir must be outside the repository or below .cache; "
            f"refusing {cache_path}"
        )
    basetemp = getattr(config.option, "basetemp", None)
    if basetemp is None:
        return
    path = Path(str(basetemp))
    basetemp_path = (path if path.is_absolute() else root / path).resolve()
    if _is_within(basetemp_path, root) and not _is_within(
        basetemp_path, safe_cache_root
    ):
        raise pytest.UsageError(
            "pytest --basetemp must be outside the repository or below .cache, "
            f"not the repository; refusing {basetemp_path}"
        )


@pytest.fixture
def project(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "app"
    root.mkdir()
    (root / "app.py").write_text(
        "from dataclasses import dataclass\n"
        "from dagcert.runtime import operation\n\n"
        "@dataclass(frozen=True)\n"
        "class WorkInput:\n"
        "    value: int\n\n"
        "@dataclass(frozen=True)\n"
        "class WorkCompleted:\n"
        "    value: int\n\n"
        "@operation\n"
        "def work(request: WorkInput) -> WorkCompleted:\n"
        "    return WorkCompleted(request.value + 1)\n",
        encoding="utf-8",
    )
    contract = root / "dag_contract.json"
    contract.write_text(json.dumps({
        "schema": "dagcert-contract/v6",
        "workers": [{"id": "worker", "concurrency": 2}],
        "resources": [{"id": "state", "capacity": 1, "initial": 0}],
        "tasks": [{
            "id": "work", "role": "operation", "worker": "worker",
            "implementation": {"language": "python", "path": "app.py", "symbol": "work"},
            "outcomes": [
                {"type": "WorkCompleted", "resources": {"state": {"acquire": 1}}, "metadata": {}},
            ],
            "error_budget": None,
            "external_contract": None,
            "depends_on": [],
            "timings": {"normal": {
                "metric": "duration", "upper_ms": 10, "minimum_samples": 3,
                "policy": "max", "safety_factor": 1.3,
            }},
        }],
        "compositions": [],
        "metadata": {},
    }, indent=2), encoding="utf-8")
    requirements = root / "english_requirements.json"
    requirements.write_text(json.dumps({
        "schema": "dagcert-english-requirements/v2",
        "claims": [{
            "id": "work-completes",
            "statement": "The declared work task completes within 10 ms for the measured source.",
            "primitive_refs": ["task:work", "timing:work/normal"],
            "checker_refs": [],
            "assumptions": [],
            "basis": "observed",
            "formula": None,
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
            outcome_type="WorkCompleted",
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
