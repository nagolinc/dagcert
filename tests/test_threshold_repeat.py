from __future__ import annotations

from pathlib import Path
import json

import pytest

from dagcert.analysis import analyze_contract
from dagcert.contract import ContractError, load_contract
from dagcert.evidence import TimingSample
from dagcert.formula import evaluate_formula


APP_SOURCE = '''from dataclasses import dataclass
from dagcert.runtime import operation

@dataclass(frozen=True)
class AttemptInput:
    value: int

@dataclass(frozen=True)
class Prepared:
    value: int

@dataclass(frozen=True)
class Rejected:
    reason: str

@operation
def prepare(request: AttemptInput) -> Prepared | Rejected:
    if request.value >= 0:
        return Prepared(request.value)
    return Rejected("negative")
'''


def _raw_contract(*, attempts: int = 10, required: int = 7) -> dict[str, object]:
    return {
        "schema": "dagcert-contract/v11",
        "workers": [{"id": "preparer", "concurrency": 4}],
        "resources": [
            {"id": "prepared", "capacity": 100, "initial": 0, "unit": "items"},
        ],
        "tasks": [{
            "id": "prepare",
            "role": "operation",
            "worker": "preparer",
            "implementation": {
                "language": "python", "path": "app.py", "symbol": "prepare",
            },
            "outcomes": [
                {
                    "type": "Prepared",
                    "resources": {"prepared": {"produce": 1}},
                    "metadata": {},
                },
                {"type": "Rejected", "resources": {}, "metadata": {}},
            ],
            "error_budget": {
                "basis": "engineering_assumption",
                "evidence_case": "completion",
                "good_outcomes": ["Prepared"],
                "bad_event_probability_upper": 0.1,
                "minimum_observations": 10,
            },
            "external_contract": None,
            "callable_bindings": [],
            "start_resources": {},
            "depends_on": [],
            "timings": {
                "completion": {
                    "metric": "duration",
                    "evidence": "assumed",
                    "upper_ms": 5,
                    "minimum_samples": 0,
                    "policy": "max",
                    "safety_factor": 1,
                },
            },
        }],
        "channels": [],
        "external_handoffs": [],
        "compositions": [{
            "id": "prepare-threshold",
            "expression": {
                "kind": "threshold_repeat",
                "attempts": attempts,
                "required": required,
                "task": "prepare",
                "timing": "completion",
                "qualifying_outcome": "Prepared",
                "resource": "prepared",
            },
            "metadata": {},
        }],
        "state_claims": [],
        "metadata": {},
    }


def _load(tmp_path: Path, raw: dict[str, object] | None = None):
    (tmp_path / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    path = tmp_path / "dag_contract.json"
    path.write_text(json.dumps(raw or _raw_contract()), encoding="utf-8")
    return load_contract(path, source_root=tmp_path)


def _analysis(contract):
    fingerprint = "f" * 64
    start_acquired = (
        {"execution-slots": 1}
        if "execution-slots" in contract.task_by_id["prepare"].start_resources
        else {}
    )
    samples = tuple(
        TimingSample(
            task_id="prepare",
            case="completion",
            value_ms=1,
            worker_id="preparer",
            source_fingerprint=fingerprint,
            outcome_type="Rejected" if index == 9 else "Prepared",
            resource_produced={} if index == 9 else {"prepared": 1},
            start_resource_acquired=start_acquired,
        )
        for index in range(10)
    )
    report = analyze_contract(contract, samples, source_fingerprint=fingerprint)
    assert report.passed, report.findings
    return report


def test_threshold_repeat_uses_markov_envelope_and_worker_waves(tmp_path: Path) -> None:
    contract = _load(tmp_path)
    analysis = _analysis(contract)

    confidence = evaluate_formula({
        "eq": [
            {"composition_success_probability_lower": "composition:prepare-threshold"},
            0.75,
        ],
    }, contract, analysis)
    latency = evaluate_formula({
        "eq": [
            {"composition_upper_ms": "composition:prepare-threshold"},
            15,
        ],
    }, contract, analysis)

    assert confidence.passed
    assert latency.passed
    assert confidence.primitive_refs == (
        "composition:prepare-threshold", "error-budget:prepare",
    )


def test_threshold_repeat_is_not_an_all_attempts_union_bound(tmp_path: Path) -> None:
    contract = _load(tmp_path)
    analysis = _analysis(contract)

    failure = evaluate_formula({
        "eq": [
            {"composition_failure_probability_upper": "composition:prepare-threshold"},
            0.25,
        ],
    }, contract, analysis)

    assert failure.passed


@pytest.mark.parametrize(
    ("attempts", "required", "message"),
    [(1, 1, "attempts must be at least 2"), (3, 4, "must not exceed attempts")],
)
def test_threshold_repeat_rejects_invalid_cardinality(
    tmp_path: Path, attempts: int, required: int, message: str,
) -> None:
    with pytest.raises(ContractError, match=message):
        _load(tmp_path, _raw_contract(attempts=attempts, required=required))


def test_threshold_repeat_requires_one_resource_unit_on_qualifying_outcome(
    tmp_path: Path,
) -> None:
    raw = _raw_contract()
    raw["tasks"][0]["outcomes"][0]["resources"]["prepared"]["produce"] = 2  # type: ignore[index]

    with pytest.raises(ContractError, match="produce exactly one"):
        _load(tmp_path, raw)


def test_threshold_repeat_rejects_ambiguous_resource_producers(tmp_path: Path) -> None:
    raw = _raw_contract()
    raw["tasks"][0]["outcomes"][1]["resources"] = {  # type: ignore[index]
        "prepared": {"produce": 1},
    }

    with pytest.raises(ContractError, match="non-qualifying outcomes also produce"):
        _load(tmp_path, raw)


def test_threshold_repeat_latency_respects_acquired_resource_capacity(
    tmp_path: Path,
) -> None:
    raw = _raw_contract()
    raw["resources"].append(  # type: ignore[union-attr]
        {"id": "execution-slots", "capacity": 2, "initial": 2, "unit": "slots"},
    )
    raw["tasks"][0]["start_resources"] = {  # type: ignore[index]
        "execution-slots": {"acquire": 1},
    }
    contract = _load(tmp_path, raw)
    analysis = _analysis(contract)

    latency = evaluate_formula({
        "eq": [
            {"composition_upper_ms": "composition:prepare-threshold"},
            25,
        ],
    }, contract, analysis)

    assert latency.passed


def test_threshold_repeat_requires_contract_v11(tmp_path: Path) -> None:
    raw = _raw_contract()
    raw["schema"] = "dagcert-contract/v10"

    with pytest.raises(ContractError, match="requires dagcert-contract/v11"):
        _load(tmp_path, raw)
