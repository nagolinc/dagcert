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


def test_nested_external_call_is_one_logical_task_not_three_nodes():
    example = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "certified_nested_external_call"
    )
    contract = load_contract(
        example / "dag_contract.json",
        source_root=example,
    )

    assert [task.id for task in contract.tasks] == ["url.normalize"]
    assert contract.tasks[0].external_calls == ("stdlib.url.unquote",)
    assert [boundary.id for boundary in contract.external_boundaries] == [
        "stdlib.url.unquote"
    ]


def test_nested_external_boundary_must_be_used_by_the_declared_task(tmp_path: Path):
    example = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "certified_nested_external_call"
    )
    raw = json.loads((example / "dag_contract.json").read_text(encoding="utf-8"))
    raw["tasks"][0]["external_calls"] = []
    contract_path = tmp_path / "unused-boundary.json"
    contract_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="must be called by at least one logical task"):
        load_contract(contract_path, source_root=example)


def test_nested_external_call_cannot_cite_an_unknown_boundary(tmp_path: Path):
    example = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "certified_nested_external_call"
    )
    raw = json.loads((example / "dag_contract.json").read_text(encoding="utf-8"))
    raw["tasks"][0]["external_calls"] = ["stdlib.url.not-declared"]
    contract_path = tmp_path / "unknown-boundary.json"
    contract_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="references unknown external boundaries"):
        load_contract(contract_path, source_root=example)


def test_resources_may_be_empty(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["resources"] = []
    raw["tasks"][0]["outcomes"][0]["resources"] = {}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_contract(path, source_root=project["root"]).resources == ()


def test_rejects_cycles(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["depends_on"] = [{"task": "work", "outcome_type": "WorkCompleted"}]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError):
        load_contract(path, source_root=project["root"])


def test_minimum_samples_must_be_integer(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["timings"]["normal"]["minimum_samples"] = 2.5
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError):
        load_contract(path, source_root=project["root"])


def test_every_task_requires_duration_timing(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["timings"]["normal"]["metric"] = "interval"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="duration"):
        load_contract(path, source_root=project["root"])


@pytest.mark.parametrize("field", ["id", "implementation", "outcomes"])
def test_task_identifiers_are_required_strings(project, tmp_path: Path, field: str):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0].pop(field)
    path = tmp_path / f"missing-{field}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError):
        load_contract(path, source_root=project["root"])


def test_dependency_ids_are_not_coerced(project, tmp_path: Path):
    raw = json.loads(Path(project["contract"]).read_text(encoding="utf-8"))
    raw["tasks"][0]["depends_on"] = [{"task": None, "outcome_type": "WorkCompleted"}]
    path = tmp_path / "bad-dependency.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ContractError, match="dependency.task must be a string"):
        load_contract(path, source_root=project["root"])
