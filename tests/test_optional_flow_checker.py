from pathlib import Path
import json

from dagcert import CheckContext, EvidenceRecorder, TimingSample, load_contract, load_evidence, load_requirements, sha256_file, source_fingerprint
from examples.optional_flow_checker import LagClaim, SupplyClaim, check_flow_guarantees


def test_four_primitives_express_supply_progress_and_generation_lag(tmp_path: Path):
    root = tmp_path / "flow-app"
    root.mkdir()
    (root / "app.py").write_text("# representative source\n", encoding="utf-8")
    contract_path = root / "dag_contract.json"
    contract_path.write_text(json.dumps({
        "schema": "dagcert-contract/v2",
        "workers": [
            {"id": "source", "concurrency": 1},
            {"id": "updater", "concurrency": 3},
            {"id": "renderer", "concurrency": 2},
        ],
        "resources": [
            {"id": "render-work", "capacity": 10, "initial": 2, "unit": "prompts"},
            {"id": "model-lag", "capacity": 3, "initial": 0, "unit": "generations"},
        ],
        "tasks": [
            {
                "id": "produce", "worker": "source", "input_type": "Input", "output_type": "Work",
                "depends_on": [],
                "resources": {"render-work": {"produce": 1}, "model-lag": {"produce": 1}},
                "timings": {
                    "duration": {"metric": "duration", "upper_ms": 50, "minimum_samples": 3},
                    "cadence": {
                        "metric": "interval", "lower_ms": 100, "upper_ms": 200,
                        "evidence": "assumed", "minimum_samples": 0,
                    },
                },
            },
            {
                "id": "update", "worker": "updater", "input_type": "Generation", "output_type": "Model",
                "depends_on": ["produce"], "resources": {"model-lag": {"consume": 1}},
                "timings": {"duration": {
                    "metric": "duration", "lower_ms": 80, "upper_ms": 250, "minimum_samples": 3,
                }},
            },
            {
                "id": "image.render", "worker": "renderer", "input_type": "Work", "output_type": "Image",
                "depends_on": ["produce"], "resources": {"render-work": {"consume": 1}},
                "timings": {"duration": {
                    "metric": "duration", "lower_ms": 500, "upper_ms": 1200, "minimum_samples": 3,
                }},
            },
        ],
    }, indent=2), encoding="utf-8")
    requirements_path = root / "english_requirements.json"
    requirements_path.write_text(json.dumps({
        "schema": "dagcert-english-requirements/v1",
        "claims": [{
            "id": "flow",
            "statement": "The declared flow is supplied and bounded.",
            "primitive_refs": ["task:produce", "task:update", "task:image.render"],
            "checker_refs": ["example.flow-guarantees/v1"],
            "assumptions": [],
        }],
        "metadata": {},
    }), encoding="utf-8")
    evidence_path = root / "artifacts" / "timings.jsonl"
    fingerprint = source_fingerprint(
        root, exclude=["dag_contract.json", "english_requirements.json"]
    )
    recorder = EvidenceRecorder(evidence_path)
    for task, values in {
        "produce": (20, 22, 24),
        "update": (140, 145, 150),
        "image.render": (700, 750, 800),
    }.items():
        worker = {"produce": "source", "update": "updater", "image.render": "renderer"}[task]
        types = {
            "produce": ("Input", "Work"),
            "update": ("Generation", "Model"),
            "image.render": ("Work", "Image"),
        }[task]
        produced = {"render-work": 1, "model-lag": 1} if task == "produce" else {}
        consumed = {"model-lag": 1} if task == "update" else {"render-work": 1} if task == "image.render" else {}
        for value in values:
            recorder.append(TimingSample(
                task_id=task, case="duration", value_ms=value, worker_id=worker,
                source_fingerprint=fingerprint, observed_input_type=types[0],
                observed_output_type=types[1], resource_consumed=consumed,
                resource_produced=produced,
            ))
    context = CheckContext(
        contract=load_contract(contract_path), timings=load_evidence(evidence_path),
        source_root=root, source_fingerprint=fingerprint,
        contract_sha256=sha256_file(contract_path), evidence_sha256=sha256_file(evidence_path),
        requirements=load_requirements(requirements_path),
        requirements_sha256=sha256_file(requirements_path),
    )
    result = check_flow_guarantees(
        context,
        supply=SupplyClaim("image.render", "duration", "produce", "cadence", "render-work"),
        lag=LagClaim("produce", "cadence", "update", "duration", "model-lag", 3),
    )
    assert result.passed
    claims = result.facts["claims"]
    assert any("not starved" in claim for claim in claims)
    assert any("no structurally blocked" in claim for claim in claims)
    assert any("3 generations" in claim for claim in claims)
