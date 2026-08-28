from dataclasses import replace
from pathlib import Path
import json

from dagcert import TimingSample, analyze_contract, load_contract, load_evidence


def test_valid_evidence_passes(project):
    report = analyze_contract(
        load_contract(project["contract"]), load_evidence(project["evidence"]),
        source_fingerprint=project["fingerprint"],
    )
    assert report.passed
    assert report.timings[0].certified_upper_ms == 3.9
    assert report.structural_progress.passed


def test_wrong_source_and_resource_excess_fail(project):
    samples = list(load_evidence(project["evidence"]))
    samples.append(TimingSample(
        task_id="work", case="normal", value_ms=1, worker_id="worker",
        source_fingerprint="wrong", outcome_type="WorkCompleted",
        resource_acquired={"state": 2},
    ))
    report = analyze_contract(load_contract(project["contract"]), samples, source_fingerprint=project["fingerprint"])
    assert not report.passed
    assert {item.code for item in report.findings} >= {"wrong-source", "resource-effect-mismatch"}


def test_structural_progress_rejects_consumer_without_supply(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["outcomes"][0]["resources"] = {"state": {"consume": 1}}
    contract_path = tmp_path / "blocked.json"
    contract_path.write_text(json.dumps(raw), encoding="utf-8")
    samples = tuple(
        replace(sample, resource_acquired={}, resource_consumed={"state": 1})
        for sample in load_evidence(project["evidence"])
    )
    report = analyze_contract(
        load_contract(contract_path, source_root=project["root"]), samples,
        source_fingerprint=project["fingerprint"],
    )
    assert not report.structural_progress.passed
    blocked = [item for item in report.findings if item.code == "structurally-blocked-task"]
    assert len(blocked) == 1
    assert "no initial supply or reachable producer" in blocked[0].message


def test_source_outcome_pipeline_is_may_reachable_but_not_must_reachable(
    project, tmp_path: Path,
):
    root = Path(project["root"])
    app = root / "app.py"
    app.write_text(app.read_text(encoding="utf-8").replace(
        "@operation\ndef work",
        "@dataclass(frozen=True)\nclass WorkRejected:\n    reason: str\n\n@operation\ndef work",
    ).replace("-> WorkCompleted:", "-> WorkCompleted | WorkRejected:") + (
        "\n@dataclass(frozen=True)\n"
        "class FollowupCompleted:\n"
        "    value: int\n\n"
        "@operation\n"
        "def followup(request: WorkCompleted) -> FollowupCompleted:\n"
        "    return FollowupCompleted(request.value)\n"
    ), encoding="utf-8")
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["outcomes"][0]["resources"] = {"state": {"produce": 1}}
    raw["tasks"][0]["outcomes"].append({
        "type": "WorkRejected", "resources": {}, "metadata": {},
    })
    raw["tasks"].append({
        "id": "followup", "role": "operation", "worker": "worker",
        "implementation": {"language": "python", "path": "app.py", "symbol": "followup"},
        "outcomes": [
            {"type": "FollowupCompleted", "resources": {"state": {"consume": 1}}, "metadata": {}},
        ],
        "error_budget": None,
        "depends_on": [{"task": "work", "outcome_type": "WorkCompleted"}],
        "timings": {"normal": {
            "metric": "duration", "upper_ms": 10, "minimum_samples": 3,
            "policy": "max", "safety_factor": 1.3,
        }},
    })
    contract_path = tmp_path / "pipeline.json"
    contract_path.write_text(json.dumps(raw), encoding="utf-8")
    fingerprint = "f" * 64
    samples = [
        replace(
            sample, source_fingerprint=fingerprint, resource_acquired={},
            resource_produced={"state": 1},
        )
        for sample in load_evidence(project["evidence"])
    ]
    samples.extend(
        TimingSample(
            task_id="followup", case="normal", value_ms=value, worker_id="worker",
            source_fingerprint=fingerprint, outcome_type="FollowupCompleted",
            resource_consumed={"state": 1},
        )
        for value in (1.0, 2.0, 3.0)
    )

    report = analyze_contract(
        load_contract(contract_path, source_root=root), samples,
        source_fingerprint=fingerprint,
    )

    assert report.passed
    assert report.structural_progress.may_reachable_tasks == ("followup", "work")
    assert report.structural_progress.must_reachable_tasks == ("work",)
    assert report.structural_progress.conditionally_reachable_tasks == ("followup",)


def test_error_budget_counts_retained_bad_outcomes_without_calling_path_blocked():
    root = Path(__file__).parents[1] / "examples" / "certified_vote"
    contract = load_contract(root / "dag_contract.json", source_root=root)
    samples = list(load_evidence(root / "artifacts" / "timings.jsonl"))
    fingerprint = samples[0].source_fingerprint
    preview_index = next(
        index for index, sample in enumerate(samples) if sample.task_id == "vote.preview"
    )
    samples[preview_index] = replace(
        samples[preview_index], outcome_type="PreviewRejected",
    )

    report = analyze_contract(contract, samples, source_fingerprint=fingerprint)

    assert not report.passed
    assert any(
        finding.code == "error-budget-observed-rate-exceeded"
        for finding in report.findings
    )
    assert not any(finding.code == "undeclared-outcome" for finding in report.findings)


def test_unexpected_exception_cannot_be_accepted_by_an_error_budget():
    root = Path(__file__).parents[1] / "examples" / "certified_vote"
    contract = load_contract(root / "dag_contract.json", source_root=root)
    samples = list(load_evidence(root / "artifacts" / "timings.jsonl"))
    fingerprint = samples[0].source_fingerprint
    preview_index = next(
        index for index, sample in enumerate(samples) if sample.task_id == "vote.preview"
    )
    samples[preview_index] = replace(
        samples[preview_index], outcome_type="dagcert.runtime.UnhandledException",
    )

    report = analyze_contract(contract, samples, source_fingerprint=fingerprint)

    assert not report.passed
    assert any(
        finding.code == "unhandled-operation-exception"
        for finding in report.findings
    )
