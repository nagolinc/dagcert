from pathlib import Path
import json

import pytest

from dagcert import ContractError, load_contract


def test_loads_only_four_primitive_contract(project):
    contract = load_contract(project["contract"])
    assert [item.id for item in contract.workers] == ["worker"]
    assert [item.id for item in contract.tasks] == ["work"]
    assert [item.id for item in contract.resources] == ["state"]
    assert contract.tasks[0].timings["normal"].upper_ms == 10


def test_resources_may_be_empty(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["resources"] = []
    raw["tasks"][0]["resources"] = {}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_contract(path).resources == ()


def test_rejects_cycles(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["depends_on"] = ["work"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError):
        load_contract(path)


def test_minimum_samples_must_be_integer(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["timings"]["normal"]["minimum_samples"] = 2.5
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError):
        load_contract(path)


def test_every_task_requires_duration_timing(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["timings"]["normal"]["metric"] = "interval"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="duration"):
        load_contract(path)


@pytest.mark.parametrize("field", ["id", "input_type", "output_type"])
def test_task_identifiers_are_required_strings(project, tmp_path: Path, field: str):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0].pop(field)
    path = tmp_path / f"missing-{field}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="string"):
        load_contract(path)


def test_dependency_ids_are_not_coerced(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["depends_on"] = [None]
    path = tmp_path / "bad-dependency.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="dependency must be a string"):
        load_contract(path)
