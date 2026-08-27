from pathlib import Path
import json

import pytest

from dagcert import ContractError, TimingSample, analyze_contract, load_contract
from dagcert.formula import FormulaError, evaluate_formula


def _contract(tmp_path: Path, *, composition_uses_observer: bool = False):
    path = tmp_path / "contract.json"
    path.write_text(json.dumps({
        "schema": "dagcert-contract/v3",
        "workers": [
            {"id": "first-worker", "concurrency": 1},
            {"id": "second-worker", "concurrency": 1},
            {"id": "observer-worker", "concurrency": 1},
        ],
        "resources": [{"id": "work", "capacity": 2, "initial": 1}],
        "tasks": [
            {
                "id": "stage.first", "role": "operation", "worker": "first-worker",
                "input_type": "Input", "output_type": "Intermediate", "depends_on": [],
                "resources": {"work": {"produce": 1}},
                "timings": {"duration": {
                    "metric": "duration", "upper_ms": 10, "minimum_samples": 1,
                    "safety_factor": 1,
                }},
            },
            {
                "id": "stage.second", "role": "operation", "worker": "second-worker",
                "input_type": "Intermediate", "output_type": "Output",
                "depends_on": ["stage.first"], "resources": {"work": {"consume": 1}},
                "timings": {"duration": {
                    "metric": "duration", "upper_ms": 20, "minimum_samples": 1,
                    "safety_factor": 1,
                }},
            },
            {
                "id": "pipeline.observe", "role": "instrumentation",
                "worker": "observer-worker", "input_type": "Batch", "output_type": "Elapsed",
                "depends_on": ["stage.first", "stage.second"], "resources": {},
                "timings": {"aggregate": {
                    "metric": "duration", "upper_ms": 100, "minimum_samples": 1,
                    "safety_factor": 1,
                }},
            },
        ],
        "compositions": [{
            "id": "pipeline",
            "steps": [
                {"task": "stage.first", "timing": "duration", "count": 1},
                {
                    "task": "pipeline.observe" if composition_uses_observer else "stage.second",
                    "timing": "aggregate" if composition_uses_observer else "duration",
                    "count": 1,
                },
            ],
            "metadata": {},
        }],
        "metadata": {},
    }), encoding="utf-8")
    return load_contract(path)


def _analysis(contract):
    fingerprint = "f" * 64
    samples = []
    for task, case, worker, value, input_type, output_type, produced, consumed in (
        ("stage.first", "duration", "first-worker", 8, "Input", "Intermediate", {"work": 1}, {}),
        ("stage.second", "duration", "second-worker", 15, "Intermediate", "Output", {}, {"work": 1}),
        ("pipeline.observe", "aggregate", "observer-worker", 25, "Batch", "Elapsed", {}, {}),
    ):
        samples.append(TimingSample(
            task_id=task, case=case, value_ms=value, worker_id=worker,
            source_fingerprint=fingerprint, observed_input_type=input_type,
            observed_output_type=output_type, resource_produced=produced,
            resource_consumed=consumed,
        ))
    return analyze_contract(contract, samples, source_fingerprint=fingerprint)


def test_measured_pipeline_observer_cannot_prove_a_derived_claim(tmp_path):
    contract = _contract(tmp_path)
    analysis = _analysis(contract)

    with pytest.raises(FormulaError, match="at least two connected tasks"):
        evaluate_formula({
            "lte": [
                {"timing_upper_ms": "timing:pipeline.observe/aggregate"},
                100,
            ]
        }, contract, analysis)


def test_instrumentation_cannot_be_hidden_inside_a_composition(tmp_path):
    with pytest.raises(ContractError, match="cannot use instrumentation"):
        _contract(tmp_path, composition_uses_observer=True)


def test_composition_bound_is_recomputed_from_operation_leaf_bounds(tmp_path):
    contract = _contract(tmp_path)
    analysis = _analysis(contract)

    evaluation = evaluate_formula({
        "eq": [{"composition_upper_ms": "composition:pipeline"}, 23]
    }, contract, analysis)

    assert evaluation.passed
    assert evaluation.composition_refs == ("composition:pipeline",)


def test_failed_attempt_makes_leaf_analysis_fail(tmp_path):
    contract = _contract(tmp_path)
    fingerprint = "f" * 64
    samples = [
        TimingSample(
            task_id="stage.first", case="duration", value_ms=8,
            worker_id="first-worker", source_fingerprint=fingerprint,
            observed_input_type="Input", observed_output_type="Intermediate",
            resource_produced={"work": 1},
        ),
        TimingSample(
            task_id="stage.first", case="duration", value_ms=10,
            worker_id="first-worker", source_fingerprint=fingerprint,
            succeeded=False,
        ),
    ]

    analysis = analyze_contract(contract, samples, source_fingerprint=fingerprint)

    assert not analysis.passed
    assert any(item.code == "failed-task-attempt" for item in analysis.findings)
