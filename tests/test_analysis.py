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
        source_fingerprint="wrong", observed_input_type="int", observed_output_type="int",
        resource_acquired={"state": 2},
    ))
    report = analyze_contract(load_contract(project["contract"]), samples, source_fingerprint=project["fingerprint"])
    assert not report.passed
    assert {item.code for item in report.findings} >= {"wrong-source", "resource-effect-mismatch"}


def test_structural_progress_rejects_consumer_without_supply(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["resources"] = {"state": {"consume": 1}}
    contract_path = tmp_path / "blocked.json"
    contract_path.write_text(json.dumps(raw), encoding="utf-8")
    samples = tuple(
        replace(sample, resource_acquired={}, resource_consumed={"state": 1})
        for sample in load_evidence(project["evidence"])
    )
    report = analyze_contract(
        load_contract(contract_path), samples, source_fingerprint=project["fingerprint"],
    )
    assert not report.structural_progress.passed
    blocked = [item for item in report.findings if item.code == "structurally-blocked-task"]
    assert len(blocked) == 1
    assert "no initial supply or reachable producer" in blocked[0].message
