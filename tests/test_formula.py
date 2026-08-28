from pathlib import Path
from dataclasses import replace
import json

import pytest

from dagcert import (
    ContractError, EnglishClaim, EnglishRequirements, TimingSample, analyze_contract,
    audit_translation, load_contract, load_evidence,
)
from dagcert.formula import FormulaError, evaluate_formula, validate_claim_formula


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


def test_finite_composition_uses_union_bound_without_independence():
    root = Path(__file__).parents[1] / "examples" / "certified_vote"
    contract = load_contract(root / "dag_contract.json", source_root=root)
    samples = load_evidence(root / "artifacts" / "timings.jsonl")
    analysis = analyze_contract(
        contract, samples, source_fingerprint=samples[0].source_fingerprint,
    )

    evaluation = evaluate_formula({
        "eq": [
            {"composition_failure_probability_upper": "composition:vote-cast"},
            0.02,
        ]
    }, contract, analysis)

    assert evaluation.passed
    assert evaluation.primitive_refs == (
        "composition:vote-cast",
        "error-budget:vote.commit",
        "error-budget:vote.preview",
    )


def test_chance_claim_cannot_hide_a_failed_probability_bound_in_true_or_branch():
    with pytest.raises(FormulaError, match="must directly compare"):
        validate_claim_formula({
            "or": [
                {
                    "gte": [
                        {"composition_success_probability_lower": "composition:vote-cast"},
                        0.999,
                    ]
                },
                {"eq": [1, 1]},
            ]
        }, basis="chance")


@pytest.mark.parametrize("threshold", [-0.01, 1.01, "0.98"])
def test_chance_claim_requires_a_literal_probability_threshold(threshold):
    with pytest.raises(FormulaError, match="literal probability|between 0 and 1"):
        validate_claim_formula({
            "gte": [
                {"composition_success_probability_lower": "composition:vote-cast"},
                threshold,
            ]
        }, basis="chance")


def test_derived_claim_cannot_use_vacuous_boolean_logic_or_self_comparison():
    with pytest.raises(FormulaError, match="can make a proof vacuous"):
        validate_claim_formula({
            "or": [
                {"lte": [{"composition_upper_ms": "composition:pipeline"}, 30]},
                {"eq": [1, 1]},
            ]
        }, basis="derived")
    with pytest.raises(FormulaError, match="compares an expression with itself"):
        validate_claim_formula({
            "eq": [
                {"composition_upper_ms": "composition:pipeline"},
                {"composition_upper_ms": "composition:pipeline"},
            ]
        }, basis="derived")


def test_error_budget_must_bound_the_exact_typed_outcome_selected_by_path():
    root = Path(__file__).parents[1] / "examples" / "certified_vote"
    contract = load_contract(root / "dag_contract.json", source_root=root)
    preview = contract.task_by_id["vote.preview"]
    assert preview.error_budget is not None
    widened_preview = replace(
        preview,
        error_budget=replace(
            preview.error_budget,
            good_outcomes=("PreviewTotal", "PreviewRejected"),
        ),
    )
    widened_contract = replace(
        contract,
        tasks=tuple(
            widened_preview if task.id == preview.id else task
            for task in contract.tasks
        ),
    )
    samples = load_evidence(root / "artifacts" / "timings.jsonl")
    analysis = analyze_contract(
        widened_contract, samples, source_fingerprint=samples[0].source_fingerprint,
    )

    with pytest.raises(FormulaError, match="does not bound failure of this typed path"):
        evaluate_formula({
            "gte": [
                {"composition_success_probability_lower": "composition:vote-cast"},
                0.98,
            ]
        }, widened_contract, analysis)


def test_error_budget_may_classify_every_real_outcome_as_good(tmp_path):
    root = Path(__file__).parents[1] / "examples" / "certified_vote"
    raw = json.loads((root / "dag_contract.json").read_text(encoding="utf-8"))
    preview = next(task for task in raw["tasks"] if task["id"] == "vote.preview")
    preview["error_budget"]["good_outcomes"] = [
        outcome["type"] for outcome in preview["outcomes"]
    ]
    path = tmp_path / "all-outcomes-good.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    contract = load_contract(path, source_root=root)
    loaded_preview = contract.task_by_id["vote.preview"]
    assert loaded_preview.error_budget is not None
    assert set(loaded_preview.error_budget.good_outcomes) == {
        "PreviewTotal", "PreviewRejected",
    }


def test_derived_claim_extra_prose_references_do_not_fake_formal_coverage(tmp_path):
    contract = _contract(tmp_path)
    requirements = EnglishRequirements(
        schema="dagcert-english-requirements/v2",
        claims=(EnglishClaim(
            id="pipeline-bound",
            statement="The real two-stage pipeline has a finite composed upper bound.",
            primitive_refs=(
                "composition:pipeline",
                "task:pipeline.observe",
                "timing:pipeline.observe/aggregate",
            ),
            basis="derived",
            formula={
                "lte": [
                    {"composition_upper_ms": "composition:pipeline"},
                    30,
                ]
            },
        ),),
    )

    audit = audit_translation(requirements, contract)

    assert not audit.passed
    assert any(
        "task:pipeline.observe" in finding and "lack an English claim" in finding
        for finding in audit.findings
    )
    assert any(
        "timing:pipeline.observe/aggregate" in finding and "lack an English claim" in finding
        for finding in audit.findings
    )
